import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MinutesEditor from './MinutesEditor';

const userId = '20000000-0000-4000-8000-000000000001';
const notetakerId = userId;
const otherUserId = '20000000-0000-4000-8000-000000000002';
const meetingId = '30000000-0000-4000-8000-000000000001';
const firstRevisionId = '40000000-0000-4000-8000-000000000001';
const latestRevisionId = '40000000-0000-4000-8000-000000000002';

const user = {
  id: userId,
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-001',
  title: 'Rapat koordinasi sintetis',
  meeting_type: 'RAPIM',
  meeting_date: '2026-10-15',
  start_time: '09:00:00',
  end_time: null,
  location: 'Ruang Uji',
  chairperson_id: otherUserId,
  notetaker_id: notetakerId,
  created_by_id: otherUserId,
  status: 'LIVE',
  created_at: '2026-10-15T08:00:00Z',
  updated_at: '2026-10-15T08:00:00Z',
  agendas: [
    {
      id: '50000000-0000-4000-8000-000000000001',
      meeting_id: meetingId,
      agenda_number: 1,
      title: 'Evaluasi sintetis',
      agenda_description: 'Agenda fixture untuk tes.',
      lead_user_id: otherUserId,
      duration_minutes: 30,
      sort_order: 1,
    },
  ],
  participants: [],
};

const firstRevision = {
  id: firstRevisionId,
  meeting_id: meetingId,
  revision_number: 1,
  content: 'Catatan awal sintetis',
  created_by_id: userId,
  created_at: '2026-10-15T08:30:00Z',
};

const latestRevision = {
  ...firstRevision,
  id: latestRevisionId,
  revision_number: 2,
  content: 'Catatan terbaru dari server',
  created_by_id: otherUserId,
  created_at: '2026-10-15T09:00:00Z',
};
const secondMeeting = {
  ...meeting,
  id: '30000000-0000-4000-8000-000000000002',
  meeting_number: 'RAPIM-2026-002',
  title: 'Rapat kedua sintetis',
};
const secondMeetingRevision = {
  ...firstRevision,
  id: '40000000-0000-4000-8000-000000000003',
  meeting_id: secondMeeting.id,
  content: 'Notulen rapat kedua',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setupEditor({
  currentUser = user,
  meetings = [meeting],
  revisions = [firstRevision],
}: {
  currentUser?: typeof user;
  meetings?: (typeof meeting)[];
  revisions?: (typeof firstRevision)[];
} = {}) {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
  fetchMock
    .mockResolvedValueOnce(jsonResponse(currentUser))
    .mockResolvedValueOnce(jsonResponse(meetings))
    .mockResolvedValueOnce(jsonResponse(revisions));
  render(<MinutesEditor />);
  return fetchMock;
}

describe('MinutesEditor', () => {
  beforeEach(() => {
    document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('loads only server meeting data and displays agenda and active revision metadata', async () => {
    const fetchMock = setupEditor();

    expect(await screen.findByRole('heading', { name: 'Editor notulensi' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /RAPIM-2026-001/ })).toBeInTheDocument();
    expect(screen.getByText('Evaluasi sintetis')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue('Catatan awal sintetis');
    expect(screen.getByText('Revisi aktif: 1')).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === `Pembuat (ID): ${userId}`),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      '/api/v1/auth/me',
      '/api/v1/meetings?limit=100&offset=0',
      `/api/v1/meetings/${meetingId}/minutes-revisions`,
    ]);
  });

  it('saves with the active base revision and uses the server response without duplicate submission', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    let resolveSave: (response: Response) => void = () => undefined;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveSave = resolve;
      }),
    );

    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.clear(editor);
    await userActions.type(editor, 'Notulen diperbarui secara eksplisit');
    const saveButton = screen.getByRole('button', { name: 'Simpan revisi' });
    await userActions.click(saveButton);
    expect(saveButton).toBeDisabled();
    await userActions.click(saveButton);

    const saveCall = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(saveCall?.[0]).toBe(`/api/v1/meetings/${meetingId}/minutes-revisions`);
    expect(JSON.parse(saveCall?.[1]?.body as string)).toEqual({
      content: 'Notulen diperbarui secara eksplisit',
      base_revision_id: firstRevisionId,
    });
    expect(new Headers(saveCall?.[1]?.headers as HeadersInit).get('X-CSRF-Token')).toBe(
      'csrf-test-token',
    );
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );

    resolveSave(
      jsonResponse(
        {
          ...firstRevision,
          id: latestRevisionId,
          revision_number: 2,
          content: 'Notulen resmi dari response server',
        },
        201,
      ),
    );
    expect(await screen.findByText('Tersimpan sebagai revisi 2.')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue(
      'Notulen resmi dari response server',
    );
  });

  it('preserves a conflicted draft and advances its base only after explicitly loading the latest revision', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes changed since the supplied base revision' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse([firstRevision, latestRevision]));

    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf lokal yang harus dipertahankan');
    await userActions.click(screen.getByRole('button', { name: 'Simpan revisi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/revisi terbaru/i);
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue(
      'Draf lokal yang harus dipertahankan',
    );
    expect(screen.getByRole('button', { name: 'Simpan revisi' })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );

    await userActions.click(screen.getByRole('button', { name: 'Muat revisi terbaru' }));
    expect(await screen.findByLabelText('Isi notulensi')).toHaveValue(
      'Catatan terbaru dari server',
    );
    expect(screen.getByText('Draf lokal yang dipertahankan')).toBeInTheDocument();
    expect(screen.getByText('Draf lokal yang harus dipertahankan')).toBeInTheDocument();
    expect(screen.getByText('Revisi aktif: 2')).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );

    await userActions.clear(screen.getByLabelText('Isi notulensi'));
    await userActions.type(
      screen.getByLabelText('Isi notulensi'),
      'Perubahan berdasarkan revisi terbaru',
    );
    await userActions.click(screen.getByRole('button', { name: 'Simpan revisi' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
        2,
      ),
    );
    const retryCall = fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')[1];
    expect(JSON.parse(retryCall[1]?.body as string)).toEqual({
      content: 'Perubahan berdasarkan revisi terbaru',
      base_revision_id: latestRevisionId,
    });
  });

  it('keeps a preserved conflict draft protected when switching meetings', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor({ meetings: [meeting, secondMeeting] });
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes changed since the supplied base revision' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse([firstRevision, latestRevision]))
      .mockResolvedValueOnce(jsonResponse([secondMeetingRevision]));
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf yang masih harus disimpan');
    await userActions.click(screen.getByRole('button', { name: 'Simpan revisi' }));
    await screen.findByRole('alert');
    await userActions.click(screen.getByRole('button', { name: 'Muat revisi terbaru' }));
    await screen.findByText('Catatan terbaru dari server');

    await userActions.selectOptions(
      screen.getByRole('combobox', { name: 'Pilih rapat' }),
      secondMeeting.id,
    );

    expect(confirmSpy).toHaveBeenCalled();
    expect(screen.getByRole('combobox', { name: 'Pilih rapat' })).toHaveValue(meeting.id);
    expect(screen.getByText('Draf yang masih harus disimpan')).toBeInTheDocument();
  });

  it('distinguishes a 409 for a meeting that is no longer LIVE and refreshes its status', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes can only be edited while the meeting is LIVE' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ ...meeting, status: 'FINAL' }));

    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf ketika rapat ditutup');
    await userActions.click(screen.getByRole('button', { name: 'Simpan revisi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/rapat.*tidak lagi LIVE/i);
    expect(await screen.findByText('FINAL')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi notulensi')).toBeDisabled();
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue('Draf ketika rapat ditutup');
    expect(screen.getByText('Draf lokal yang dipertahankan').nextElementSibling).toHaveTextContent(
      'Draf ketika rapat ditutup',
    );
    expect(screen.queryByRole('button', { name: 'Muat revisi terbaru' })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(`/api/v1/meetings/${meetingId}`);
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );
  });

  it('keeps the editor locked if meeting status cannot be refreshed', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes can only be edited while the meeting is LIVE' }, 409),
      )
      .mockRejectedValueOnce(new Error('Network unavailable'))
      .mockResolvedValueOnce(jsonResponse({ ...meeting, status: 'FINAL' }));

    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf tetap terlindungi');
    await userActions.click(screen.getByRole('button', { name: 'Simpan revisi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /status rapat belum dapat diperbarui/i,
    );
    expect(screen.getByLabelText('Isi notulensi')).toBeDisabled();
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue('Draf tetap terlindungi');
    expect(screen.getByRole('button', { name: 'Muat ulang status rapat' })).toBeInTheDocument();

    await userActions.click(screen.getByRole('button', { name: 'Muat ulang status rapat' }));
    expect(await screen.findByText('FINAL')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi notulensi')).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );
  });

  it('shows readable revisions but does not let a non-notetaker edit', async () => {
    setupEditor({ currentUser: { ...user, id: otherUserId, roles: ['REKTOR'] } });

    expect(await screen.findByLabelText('Isi notulensi')).toHaveValue('Catatan awal sintetis');
    expect(screen.getByLabelText('Isi notulensi')).toBeDisabled();
    expect(screen.getByText(/Hanya notulis yang ditunjuk dapat menyunting/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Simpan revisi' })).not.toBeInTheDocument();
  });

  it('does not offer editing after a meeting is finalized', async () => {
    setupEditor({ meetings: [{ ...meeting, status: 'FINAL' }] });

    expect(await screen.findByLabelText('Isi notulensi')).toHaveValue('Catatan awal sintetis');
    expect(screen.getByLabelText('Isi notulensi')).toBeDisabled();
    expect(screen.getByText(/Rapat tidak sedang berlangsung/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Simpan revisi' })).not.toBeInTheDocument();
  });

  it('does not request meeting data for a Super Admin session', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ ...user, roles: ['SEKRETARIAT', 'SUPER_ADMIN'] }));
    vi.stubGlobal('fetch', fetchMock);
    render(<MinutesEditor />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/tidak memiliki akses/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reports an expired session without requesting meetings', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'Authentication required' }, 401));
    vi.stubGlobal('fetch', fetchMock);
    render(<MinutesEditor />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/sesi tidak aktif/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('shows API validation errors without discarding the unsaved text', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'Minutes content must not be blank' }, 422),
    );

    const editor = await screen.findByLabelText('Isi notulensi');
    await userActions.clear(editor);
    await userActions.type(editor, '   ');
    await userActions.click(screen.getByRole('button', { name: 'Simpan revisi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Minutes content must not be blank');
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue('   ');
  });

  it('shows an empty state when the meeting has no revision history', async () => {
    setupEditor({ revisions: [] });

    expect(await screen.findByText('Belum ada revisi aktif')).toBeInTheDocument();
    const history = screen.getByText(/Riwayat revisi/).closest('details');
    expect(history).not.toBeNull();
    expect(
      await within(history as HTMLElement).findByText('Belum ada revisi notulensi.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Isi notulensi')).toHaveValue('');
    expect(screen.getByText('Belum ada revisi aktif')).toBeInTheDocument();
  });
});
