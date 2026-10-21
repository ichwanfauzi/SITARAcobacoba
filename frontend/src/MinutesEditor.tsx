import { useEffect, useRef, useState } from 'react';
import {
  ApiError,
  canAccessMinutes,
  createMinutesRevision,
  getCurrentUser,
  getMeeting,
  getMeetings,
  getMinutesRevisions,
  type AuthenticatedUser,
  type MeetingSummary,
  type MinutesRevision,
} from './api';

type LoadState = 'loading' | 'ready' | 'empty' | 'failed';
type SaveState = 'clean' | 'saved' | 'saving' | 'conflict' | 'statusChanged' | 'error' | 'reloaded';

const STALE_REVISION_DETAIL = 'Minutes changed since the supplied base revision';
const MEETING_NOT_LIVE_DETAIL = 'Minutes can only be edited while the meeting is LIVE';
export const UNSAVED_MINUTES_NAVIGATION_WARNING =
  'Perubahan notulensi belum disimpan. Tinggalkan halaman dan buang draf?';

const RESTRICTED_ROLES = new Set(['PIC', 'SUPER_ADMIN']);

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function accessErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Editor tidak dapat dimuat. Coba lagi.';
  if (error.status === 401) return 'Sesi tidak aktif. Silakan login kembali lalu buka editor.';
  if (error.status === 403 || error.status === 404) {
    return 'Akun ini tidak memiliki akses ke rapat atau notulensi tersebut.';
  }
  return error.message;
}

function sortRevisions(revisions: MinutesRevision[]): MinutesRevision[] {
  return [...revisions].sort((left, right) => left.revision_number - right.revision_number);
}

function activeRevision(revisions: MinutesRevision[]): MinutesRevision | null {
  return sortRevisions(revisions).at(-1) ?? null;
}

function MinutesEditor({
  authenticatedUser,
  onPendingDraftChange,
}: {
  authenticatedUser?: AuthenticatedUser;
  onPendingDraftChange?: (hasPendingDraft: boolean) => void;
}) {
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState('');
  const [revisions, setRevisions] = useState<MinutesRevision[]>([]);
  const [content, setContent] = useState('');
  const [baselineContent, setBaselineContent] = useState('');
  const [baseRevisionId, setBaseRevisionId] = useState<string | null>(null);
  const [loadingRevisions, setLoadingRevisions] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>('clean');
  const [conflictDraft, setConflictDraft] = useState<string | null>(null);
  const [refreshingMeetingStatus, setRefreshingMeetingStatus] = useState(false);
  const [meetingStatusRefreshFailed, setMeetingStatusRefreshFailed] = useState(false);
  const requestSequence = useRef(0);
  const selectedMeeting = meetings.find((meeting) => meeting.id === selectedMeetingId) ?? null;
  const latestRevision = activeRevision(revisions);
  const hasRestrictedRole = currentUser?.roles.some((role) => RESTRICTED_ROLES.has(role)) ?? true;
  const canEdit = Boolean(
    currentUser &&
    selectedMeeting &&
    !hasRestrictedRole &&
    selectedMeeting.status === 'LIVE' &&
    saveState !== 'statusChanged' &&
    selectedMeeting.notetaker_id === currentUser.id,
  );
  const isDirty = content !== baselineContent;
  const hasPendingDraft = isDirty || conflictDraft !== null;

  useEffect(() => {
    onPendingDraftChange?.(hasPendingDraft);
    return () => onPendingDraftChange?.(false);
  }, [hasPendingDraft, onPendingDraftChange]);

  useEffect(() => {
    let mounted = true;

    async function loadEditor(): Promise<void> {
      try {
        const user = authenticatedUser ?? (await getCurrentUser());
        if (!canAccessMinutes(user)) {
          throw new ApiError('Akun ini tidak memiliki akses ke editor notulensi.', 403);
        }
        const accessibleMeetings = await getMeetings();
        if (!mounted) return;
        setCurrentUser(user);
        setMeetings(accessibleMeetings);
        if (accessibleMeetings.length === 0) {
          setLoadState('empty');
          return;
        }

        const firstMeeting = accessibleMeetings[0];
        setSelectedMeetingId(firstMeeting.id);
        const meetingRevisions = sortRevisions(await getMinutesRevisions(firstMeeting.id));
        if (!mounted) return;
        setRevisions(meetingRevisions);
        const latest = activeRevision(meetingRevisions);
        setContent(latest?.content ?? '');
        setBaselineContent(latest?.content ?? '');
        setBaseRevisionId(latest?.id ?? null);
        setLoadState('ready');
      } catch (error) {
        if (!mounted) return;
        setErrorMessage(accessErrorMessage(error));
        setLoadState('failed');
      }
    }

    void loadEditor();
    return () => {
      mounted = false;
      requestSequence.current += 1;
    };
  }, [authenticatedUser]);

  async function loadMeetingRevisions(meetingId: string, preserveDraft = false): Promise<void> {
    const requestId = ++requestSequence.current;
    const localDraft = preserveDraft ? content : null;
    setLoadingRevisions(true);
    setErrorMessage(null);
    try {
      const meetingRevisions = sortRevisions(await getMinutesRevisions(meetingId));
      if (requestId !== requestSequence.current) return;
      const latest = activeRevision(meetingRevisions);
      setRevisions(meetingRevisions);
      setBaseRevisionId(latest?.id ?? null);
      setBaselineContent(latest?.content ?? '');
      setContent(latest?.content ?? '');
      setConflictDraft(localDraft);
      setSaveState(preserveDraft ? 'reloaded' : 'clean');
    } catch (error) {
      if (requestId !== requestSequence.current) return;
      setErrorMessage(accessErrorMessage(error));
      if (!preserveDraft) setSaveState('error');
    } finally {
      if (requestId === requestSequence.current) setLoadingRevisions(false);
    }
  }

  async function handleMeetingChange(meetingId: string): Promise<void> {
    if (
      !meetingId ||
      meetingId === selectedMeetingId ||
      loadingRevisions ||
      refreshingMeetingStatus ||
      saveState === 'saving'
    ) {
      return;
    }
    if (hasPendingDraft && !window.confirm(UNSAVED_MINUTES_NAVIGATION_WARNING)) {
      return;
    }

    setSelectedMeetingId(meetingId);
    setRevisions([]);
    setContent('');
    setBaselineContent('');
    setBaseRevisionId(null);
    setConflictDraft(null);
    setSaveState('clean');
    setMeetingStatusRefreshFailed(false);
    await loadMeetingRevisions(meetingId);
  }

  async function refreshMeetingStatus(meetingId: string): Promise<void> {
    setRefreshingMeetingStatus(true);
    setMeetingStatusRefreshFailed(false);
    try {
      const updatedMeeting = await getMeeting(meetingId);
      setMeetings((previousMeetings) =>
        previousMeetings.map((meeting) =>
          meeting.id === updatedMeeting.id ? { ...meeting, ...updatedMeeting } : meeting,
        ),
      );
    } catch {
      setMeetingStatusRefreshFailed(true);
      setErrorMessage(
        'Rapat tidak lagi LIVE. Draf Anda dipertahankan, tetapi status rapat belum dapat diperbarui. Coba muat ulang status rapat.',
      );
    } finally {
      setRefreshingMeetingStatus(false);
    }
  }

  async function handleSave(): Promise<void> {
    if (!canEdit || !selectedMeeting || !isDirty || loadingRevisions || saveState === 'saving') {
      return;
    }

    setSaveState('saving');
    setErrorMessage(null);
    try {
      const savedRevision = await createMinutesRevision(
        selectedMeeting.id,
        content,
        baseRevisionId,
      );
      const updatedRevisions = sortRevisions([...revisions, savedRevision]);
      setRevisions(updatedRevisions);
      setBaseRevisionId(savedRevision.id);
      setContent(savedRevision.content);
      setBaselineContent(savedRevision.content);
      setConflictDraft(null);
      setSaveState('saved');
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.message === STALE_REVISION_DETAIL
      ) {
        setConflictDraft(content);
        setErrorMessage(
          'Ada revisi terbaru. Draf Anda dipertahankan; muat revisi terbaru sebelum melanjutkan.',
        );
        setSaveState('conflict');
      } else if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.message === MEETING_NOT_LIVE_DETAIL
      ) {
        setConflictDraft(content);
        setSaveState('statusChanged');
        setErrorMessage('Rapat tidak lagi LIVE. Draf Anda dipertahankan dan tidak dikirim ulang.');
        await refreshMeetingStatus(selectedMeeting.id);
      } else {
        setErrorMessage(accessErrorMessage(error));
        setSaveState('error');
      }
    }
  }

  async function handleReloadLatest(): Promise<void> {
    if (!selectedMeeting || loadingRevisions || saveState === 'saving') return;
    await loadMeetingRevisions(selectedMeeting.id, true);
  }

  async function handleReloadMeetingStatus(): Promise<void> {
    if (!selectedMeeting || refreshingMeetingStatus) return;
    await refreshMeetingStatus(selectedMeeting.id);
  }

  return (
    <section className="minutes-page" aria-labelledby="minutes-page-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">RAPIM · NOTULENSI</p>
          <h1 id="minutes-page-title">Editor notulensi</h1>
          <p className="page-description">
            Perubahan disimpan sebagai revisi baru setelah dikonfirmasi server.
          </p>
        </div>
      </div>

      {loadState === 'loading' && <p role="status">Memuat rapat dan revisi notulensi…</p>}
      {loadState === 'failed' && (
        <p className="minutes-alert" role="alert">
          {errorMessage}
        </p>
      )}
      {loadState === 'empty' && (
        <div className="minutes-empty" role="status">
          Tidak ada rapat yang dapat diakses.
        </div>
      )}

      {loadState === 'ready' && selectedMeeting && (
        <div className="minutes-layout">
          <section
            className="surface-panel minutes-context"
            aria-labelledby="meeting-context-title"
          >
            <div className="section-heading">
              <div>
                <p className="section-kicker">KONTEKS RAPAT</p>
                <h2 id="meeting-context-title">Pilih rapat</h2>
              </div>
              <span
                className={`meeting-status meeting-status--${selectedMeeting.status.toLowerCase()}`}
              >
                {selectedMeeting.status}
              </span>
            </div>

            <label className="minutes-field-label" htmlFor="minutes-meeting-select">
              Rapat yang dibuka
            </label>
            <select
              id="minutes-meeting-select"
              aria-label="Pilih rapat"
              className="minutes-select"
              value={selectedMeetingId}
              disabled={loadingRevisions || refreshingMeetingStatus || saveState === 'saving'}
              onChange={(event) => void handleMeetingChange(event.target.value)}
            >
              {meetings.map((meeting) => (
                <option key={meeting.id} value={meeting.id}>
                  {meeting.meeting_number} · {meeting.title}
                </option>
              ))}
            </select>

            <div className="minutes-meeting-meta">
              <h3>{selectedMeeting.title}</h3>
              <p>
                <strong>{selectedMeeting.meeting_number}</strong>
                <span> · </span>
                {formatDate(selectedMeeting.meeting_date)}
              </p>
            </div>

            <div className="minutes-agendas">
              <h3>Agenda</h3>
              {selectedMeeting.agendas.length > 0 ? (
                <ol>
                  {selectedMeeting.agendas.map((agenda) => (
                    <li key={agenda.id}>
                      <span>{agenda.title}</span>
                      {agenda.agenda_description && <small>{agenda.agenda_description}</small>}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="minutes-muted">Belum ada agenda pada data rapat ini.</p>
              )}
            </div>

            <div className="minutes-active-revision" aria-live="polite">
              <p className="section-kicker">REVISI AKTIF</p>
              {latestRevision ? (
                <>
                  <strong>Revisi aktif: {latestRevision.revision_number}</strong>
                  <span>Pembuat (ID): {latestRevision.created_by_id}</span>
                  <span>Dibuat {formatTimestamp(latestRevision.created_at)}</span>
                </>
              ) : (
                <strong>Belum ada revisi aktif</strong>
              )}
            </div>

            <details className="minutes-history">
              <summary>Riwayat revisi ({revisions.length})</summary>
              {revisions.length > 0 ? (
                <ol>
                  {sortRevisions(revisions)
                    .slice()
                    .reverse()
                    .map((revision) => (
                      <li key={revision.id}>
                        <strong>Revisi {revision.revision_number}</strong>
                        <span>{formatTimestamp(revision.created_at)}</span>
                      </li>
                    ))}
                </ol>
              ) : (
                <p>Belum ada revisi notulensi.</p>
              )}
            </details>
          </section>

          <section
            className="surface-panel minutes-editor-panel"
            aria-labelledby="minutes-editor-title"
          >
            <div className="section-heading">
              <div>
                <p className="section-kicker">ISI RESMI</p>
                <h2 id="minutes-editor-title">Notulensi rapat</h2>
              </div>
              {canEdit ? (
                <span className="minutes-role-badge">Notulis yang ditunjuk</span>
              ) : (
                <span className="minutes-role-badge minutes-role-badge--readonly">Baca saja</span>
              )}
            </div>

            {errorMessage && (
              <p className="minutes-alert" role="alert">
                {errorMessage}
              </p>
            )}
            {saveState === 'reloaded' && (
              <p className="minutes-notice" role="status">
                Revisi terbaru dimuat. Draf lokal tidak dikirim ulang.
              </p>
            )}
            {conflictDraft !== null && (
              <details className="minutes-preserved-draft" open>
                <summary>Draf lokal yang dipertahankan</summary>
                <pre>{conflictDraft}</pre>
              </details>
            )}

            <label className="minutes-field-label" htmlFor="minutes-content">
              Isi notulensi
            </label>
            <textarea
              id="minutes-content"
              className="minutes-textarea"
              rows={18}
              maxLength={1_000_000}
              value={content}
              disabled={!canEdit || loadingRevisions || saveState === 'saving'}
              onChange={(event) => {
                setContent(event.target.value);
                if (saveState === 'conflict') setConflictDraft(event.target.value);
                if (saveState === 'saved' || saveState === 'error' || saveState === 'reloaded') {
                  setSaveState('clean');
                  setErrorMessage(null);
                }
              }}
            />

            <div className="minutes-editor-footer">
              <p className={`minutes-save-state minutes-save-state--${saveState}`} role="status">
                {loadingRevisions
                  ? 'Memuat revisi…'
                  : saveState === 'saving'
                    ? 'Menyimpan revisi…'
                    : saveState === 'saved'
                      ? `Tersimpan sebagai revisi ${latestRevision?.revision_number ?? ''}.`
                      : saveState === 'conflict'
                        ? 'Penyimpanan tertahan karena revisi berubah.'
                        : saveState === 'statusChanged'
                          ? 'Draf dipertahankan; rapat tidak lagi LIVE.'
                          : saveState === 'error'
                            ? 'Penyimpanan gagal.'
                            : saveState === 'reloaded'
                              ? 'Revisi terbaru sudah dimuat.'
                              : isDirty
                                ? 'Perubahan belum disimpan.'
                                : latestRevision
                                  ? 'Notulensi mengikuti revisi server.'
                                  : 'Belum ada revisi notulensi.'}
              </p>
              <div className="minutes-actions">
                {saveState === 'conflict' && (
                  <button
                    className="button button--secondary"
                    type="button"
                    disabled={loadingRevisions}
                    onClick={() => void handleReloadLatest()}
                  >
                    {loadingRevisions ? 'Memuat…' : 'Muat revisi terbaru'}
                  </button>
                )}
                {meetingStatusRefreshFailed && (
                  <button
                    className="button button--secondary"
                    type="button"
                    disabled={refreshingMeetingStatus}
                    onClick={() => void handleReloadMeetingStatus()}
                  >
                    {refreshingMeetingStatus ? 'Memuat status…' : 'Muat ulang status rapat'}
                  </button>
                )}
                {canEdit && selectedMeeting.status === 'LIVE' && (
                  <button
                    className="button button--primary"
                    type="button"
                    disabled={
                      !isDirty ||
                      loadingRevisions ||
                      saveState === 'saving' ||
                      saveState === 'conflict'
                    }
                    onClick={() => void handleSave()}
                  >
                    {saveState === 'saving' ? 'Menyimpan…' : 'Simpan revisi'}
                  </button>
                )}
              </div>
            </div>

            {saveState === 'statusChanged' && (
              <p className="minutes-readonly-note">
                Status rapat berubah. Draf yang belum tersimpan dipertahankan dan penyuntingan
                dinonaktifkan.
              </p>
            )}
            {!canEdit && saveState !== 'statusChanged' && (
              <p className="minutes-readonly-note">
                {selectedMeeting.status !== 'LIVE'
                  ? 'Rapat tidak sedang berlangsung; notulensi hanya dapat dibaca.'
                  : 'Hanya notulis yang ditunjuk dapat menyunting selama rapat berlangsung.'}
              </p>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

export default MinutesEditor;
