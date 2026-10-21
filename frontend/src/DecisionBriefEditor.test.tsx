import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DecisionBriefEditor from './DecisionBriefEditor';

const meetingId = '30000000-0000-4000-8000-000000000001';
const revisionId = '40000000-0000-4000-8000-000000000001';
const decisionId = '70000000-0000-4000-8000-000000000001';

const user = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-001',
  title: 'Rapat sintetis Decision Brief',
  meeting_date: '2026-10-15',
  notetaker_id: user.id,
  status: 'FINAL',
  agendas: [
    {
      id: '50000000-0000-4000-8000-000000000001',
      agenda_number: 1,
      title: 'Evaluasi layanan',
      agenda_description: null,
      sort_order: 1,
    },
  ],
};

const revisions = [
  {
    id: revisionId,
    meeting_id: meetingId,
    revision_number: 3,
    format_version: 2,
    content: null,
    discussions: [
      {
        id: '60000000-0000-4000-8000-000000000001',
        agenda_id: meeting.agendas[0].id,
        discussion_number: 1,
        subject: 'Evaluasi triwulan',
        content: 'Catatan pembahasan sintetis',
        decisions: [
          {
            id: decisionId,
            discussion_id: '60000000-0000-4000-8000-000000000001',
            decision_number: 1,
            decision_text: 'Lengkapi laporan triwulan',
            output_expected: 'Laporan revisi',
            target_date: '2026-11-30',
            is_action_item: true,
          },
        ],
      },
    ],
    created_by_id: user.id,
    created_at: '2026-10-15T09:00:00Z',
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
});

describe('DecisionBriefEditor', () => {
  it('shows decision provenance, appends a draft, and displays its source in history', async () => {
    const userActions = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let createdVersion: Record<string, unknown> | null = null;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
        if (url.endsWith('/decision-briefs') && init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          expect(body.source_minutes_revision_id).toBe(revisionId);
          expect(body.summary).toBe('Prioritaskan pelaporan triwulan.');
          expect(body.notes).toBe('Catatan editorial sintetis.');
          expect(body.decisions).toEqual([
            {
              decision_id: decisionId,
              priority: 'Prioritas utama',
              editorial_note: 'Koordinasikan antarunit.',
            },
          ]);
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          createdVersion = {
            id: '80000000-0000-4000-8000-000000000001',
            meeting_id: meetingId,
            source_minutes_revision_id: revisionId,
            version_number: 1,
            summary: body.summary,
            notes: body.notes,
            created_by_id: user.id,
            created_at: '2026-10-15T10:00:00Z',
            is_stale: false,
            decisions: [
              {
                decision_id: decisionId,
                source_decision_text: 'Lengkapi laporan triwulan',
                source_agenda_id: meeting.agendas[0].id,
                source_agenda_title: 'Evaluasi layanan',
                source_discussion_id: '60000000-0000-4000-8000-000000000001',
                source_discussion_subject: 'Evaluasi triwulan',
                priority: 'Prioritas utama',
                editorial_note: 'Koordinasikan antarunit.',
                position: 1,
              },
            ],
          };
          return jsonResponse(createdVersion, 201);
        }
        if (url.endsWith('/decision-briefs')) return jsonResponse([]);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} />);

    expect(await screen.findByText('Lengkapi laporan triwulan')).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === 'P' && element.textContent?.includes('Revisi notulensi 3') === true,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Evaluasi layanan · Evaluasi triwulan/)).toBeInTheDocument();

    await userActions.type(
      screen.getByRole('textbox', { name: 'Ringkasan editorial' }),
      'Prioritaskan pelaporan triwulan.',
    );
    await userActions.type(
      screen.getByRole('textbox', { name: 'Catatan brief (opsional)' }),
      'Catatan editorial sintetis.',
    );
    await userActions.click(screen.getByRole('checkbox', { name: 'Lengkapi laporan triwulan' }));
    await userActions.type(screen.getByLabelText('Prioritas editorial'), 'Prioritas utama');
    await userActions.type(
      screen.getByLabelText('Catatan editorial (opsional)'),
      'Koordinasikan antarunit.',
    );
    await userActions.click(screen.getByRole('button', { name: 'Simpan versi draf' }));

    expect(
      await screen.findByText('Decision Brief versi 1 tersimpan sebagai draf.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Versi 1' })).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === 'SPAN' && element.textContent?.includes('Prioritas utama') === true,
      ),
    ).toBeInTheDocument();
    expect(createdVersion).not.toBeNull();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });

  it('preserves the attempted draft on a stale source conflict without resubmitting it', async () => {
    const userActions = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const latestRevision = {
      ...revisions[0],
      id: '40000000-0000-4000-8000-000000000002',
      revision_number: 4,
      discussions: [
        {
          ...revisions[0].discussions[0],
          id: '60000000-0000-4000-8000-000000000002',
          decisions: [
            {
              ...revisions[0].discussions[0].decisions[0],
              id: '70000000-0000-4000-8000-000000000002',
              decision_text: 'Gunakan indikator layanan terbaru',
            },
          ],
        },
      ],
    };
    let minutesReads = 0;
    let briefWrites = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url.endsWith('/minutes-revisions')) {
          minutesReads += 1;
          return jsonResponse(minutesReads === 1 ? revisions : [latestRevision]);
        }
        if (url.endsWith('/decision-briefs') && init?.method === 'POST') {
          briefWrites += 1;
          return jsonResponse({ detail: 'Notulensi telah berubah.' }, 409);
        }
        if (url.endsWith('/decision-briefs')) return jsonResponse([]);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} />);

    await userActions.type(
      await screen.findByRole('textbox', { name: 'Ringkasan editorial' }),
      'Prioritas yang sedang disusun.',
    );
    await userActions.type(
      screen.getByRole('textbox', { name: 'Catatan brief (opsional)' }),
      'Catatan yang belum tersimpan.',
    );
    await userActions.click(screen.getByRole('checkbox', { name: 'Lengkapi laporan triwulan' }));
    await userActions.type(screen.getByLabelText('Prioritas editorial'), 'Prioritas utama');
    await userActions.type(
      screen.getByLabelText('Catatan editorial (opsional)'),
      'Verifikasi angka sebelum distribusi.',
    );
    await userActions.click(screen.getByRole('button', { name: 'Simpan versi draf' }));

    expect(await screen.findByRole('heading', { name: 'Draf yang belum tersimpan' })).toBeVisible();
    expect(screen.getAllByText('Prioritas yang sedang disusun.')).toHaveLength(2);
    expect(screen.getAllByText('Catatan yang belum tersimpan.')).toHaveLength(2);
    expect(screen.getByText('Lengkapi laporan triwulan')).toBeVisible();
    expect(screen.getByText('Prioritas: Prioritas utama')).toBeVisible();
    expect(screen.getByText('Gunakan indikator layanan terbaru')).toBeVisible();
    expect(briefWrites).toBe(1);
    expect(minutesReads).toBe(2);
  });
});
