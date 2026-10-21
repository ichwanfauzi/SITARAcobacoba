import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
});

describe('SITARA dashboard', () => {
  it('shows the product identity, navigation, and operational summaries', () => {
    render(<App />);

    expect(screen.getByRole('link', { name: 'SITARA, ke dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Sistem Informasi Tindak Lanjut dan Arsip Rapat')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Ringkasan operasional' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Navigasi utama' })).toBeInTheDocument();
    expect(screen.getByText('Data contoh')).toBeInTheDocument();
    expect(screen.getByText('Rapat tahun ini')).toBeInTheDocument();
    expect(screen.getByText('Total keputusan')).toBeInTheDocument();
    expect(screen.getByText('Action items')).toBeInTheDocument();
    expect(screen.getByText('Tugas terlambat')).toBeInTheDocument();
  });

  it('filters follow-up rows by the search query', async () => {
    const user = userEvent.setup();
    render(<App />);

    const followUpList = screen.getByRole('region', { name: 'Tindak lanjut perlu perhatian' });
    expect(
      within(followUpList).getByText('Evaluasi tindak lanjut kerja sama industri'),
    ).toBeInTheDocument();

    await user.type(
      screen.getByRole('searchbox', { name: 'Cari rapat atau tindak lanjut' }),
      'arsip',
    );

    expect(
      within(followUpList).queryByText('Evaluasi tindak lanjut kerja sama industri'),
    ).not.toBeInTheDocument();
    expect(
      within(followUpList).getByText('Penataan arsip keputusan semester genap'),
    ).toBeInTheDocument();
  });

  it('opens the notulensi editor from workspace navigation', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              id: '20000000-0000-4000-8000-000000000001',
              email: 'sekretariat@example.test',
              full_name: 'Sekretariat Uji',
              roles: ['SEKRETARIAT'],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify([]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
    );
    render(<App />);

    await user.click(await screen.findByRole('link', { name: 'Notulensi' }));

    expect(await screen.findByRole('heading', { name: 'Editor notulensi' })).toBeInTheDocument();
    expect(await screen.findByText('Tidak ada rapat yang dapat diakses.')).toBeInTheDocument();
  });

  it('opens the Decision Brief editor for an authenticated meeting reader', async () => {
    window.history.replaceState(null, '', '#dashboard');
    const userActions = userEvent.setup();
    const meetingId = '30000000-0000-4000-8000-000000000001';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/auth/me') {
          return new Response(
            JSON.stringify({
              id: '20000000-0000-4000-8000-000000000001',
              email: 'sekretariat@example.test',
              full_name: 'Sekretariat Uji',
              roles: ['SEKRETARIAT'],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url === '/api/v1/meetings?limit=100&offset=0') {
          return new Response(
            JSON.stringify([
              {
                id: meetingId,
                meeting_number: 'RAPIM-2026-001',
                title: 'Rapat sintetis',
                meeting_date: '2026-10-15',
                notetaker_id: null,
                status: 'FINAL',
                agendas: [],
              },
            ]),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url.endsWith('/minutes-revisions') || url.endsWith('/decision-briefs')) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    await userActions.click(await screen.findByRole('link', { name: 'Decision Brief' }));

    expect(await screen.findByRole('heading', { name: 'Decision Brief' })).toBeInTheDocument();
    expect(
      await screen.findByText('Rapat ini belum memiliki revisi notulensi.'),
    ).toBeInTheDocument();
  });

  it('does not show the notulensi menu to PIC', async () => {
    const fetchMock = vi.fn();
    let resolveAuth: (response: Response) => void = () => undefined;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveAuth = resolve;
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolveAuth(
        new Response(
          JSON.stringify({
            id: '20000000-0000-4000-8000-000000000001',
            email: 'pic@example.test',
            full_name: 'PIC Uji',
            roles: ['PIC'],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    });

    expect(screen.queryByRole('link', { name: 'Notulensi' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Decision Brief' })).not.toBeInTheDocument();
  });

  it('guards in-app and browser navigation while a minutes draft is unsaved', async () => {
    window.history.replaceState(null, '', '#dashboard');
    const userActions = userEvent.setup();
    const meetingId = '30000000-0000-4000-8000-000000000001';
    const revisionId = '40000000-0000-4000-8000-000000000001';
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: '20000000-0000-4000-8000-000000000001',
            email: 'sekretariat@example.test',
            full_name: 'Sekretariat Uji',
            roles: ['SEKRETARIAT'],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              id: meetingId,
              meeting_number: 'RAPIM-2026-001',
              title: 'Rapat sintetis',
              meeting_date: '2026-10-15T09:00:00Z',
              notetaker_id: '20000000-0000-4000-8000-000000000001',
              status: 'LIVE',
              agendas: [],
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              id: revisionId,
              meeting_id: meetingId,
              revision_number: 1,
              content: 'Notulensi awal sintetis',
              created_by_id: '20000000-0000-4000-8000-000000000001',
              created_at: '2026-10-15T09:30:00Z',
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    vi.stubGlobal('fetch', fetchMock);
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    render(<App />);

    await userActions.click(await screen.findByRole('link', { name: 'Notulensi' }));
    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.type(editor, ' draf belum tersimpan');
    await userActions.click(screen.getByRole('link', { name: 'Dashboard' }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(window.location.hash).toBe('#notulensi');
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue(
      'Notulensi awal sintetis draf belum tersimpan',
    );

    window.location.hash = '#dashboard';
    await waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(2));
    expect(window.location.hash).toBe('#notulensi');
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue(
      'Notulensi awal sintetis draf belum tersimpan',
    );

    const beforeUnload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);

    confirmSpy.mockReturnValueOnce(true);
    await userActions.click(screen.getByRole('link', { name: 'Dashboard' }));
    await waitFor(() => expect(screen.queryByLabelText('Isi notulensi')).not.toBeInTheDocument());
    expect(window.location.hash).toBe('#dashboard');
  });
});
