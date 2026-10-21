import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  ApiError,
  canCreateDecisionBrief,
  createDecisionBriefVersion,
  getDecisionBriefHistory,
  getMeetings,
  getMinutesRevisions,
  type AuthenticatedUser,
  type DecisionBriefVersion,
  type MeetingSummary,
  type MinutesDecision,
  type MinutesRevision,
} from './api';

interface DecisionSource {
  decision: MinutesDecision;
  agendaTitle: string;
  discussionSubject: string | null;
}

interface DecisionBriefEditorProps {
  authenticatedUser: AuthenticatedUser;
}

interface PreservedBriefDraft {
  sourceRevisionId: string;
  sourceRevisionNumber: number;
  summary: string;
  notes: string;
  decisions: Array<{
    sourceText: string;
    agendaTitle: string;
    discussionSubject: string | null;
    priority: string;
    editorialNote: string;
  }>;
}

function activeRevisionOf(revisions: MinutesRevision[]): MinutesRevision | null {
  return revisions.reduce<MinutesRevision | null>(
    (active, revision) =>
      active === null || revision.revision_number > active.revision_number ? revision : active,
    null,
  );
}

function DecisionBriefEditor({ authenticatedUser }: DecisionBriefEditorProps) {
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState('');
  const [revisions, setRevisions] = useState<MinutesRevision[]>([]);
  const [history, setHistory] = useState<DecisionBriefVersion[]>([]);
  const [meetingsLoading, setMeetingsLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [summary, setSummary] = useState('');
  const [notes, setNotes] = useState('');
  const [selectedDecisionIds, setSelectedDecisionIds] = useState<Set<string>>(new Set());
  const [priorities, setPriorities] = useState<Record<string, string>>({});
  const [editorialNotes, setEditorialNotes] = useState<Record<string, string>>({});
  const [preservedDraft, setPreservedDraft] = useState<PreservedBriefDraft | null>(null);

  const canCreate = canCreateDecisionBrief(authenticatedUser);
  const selectedMeeting = meetings.find((meeting) => meeting.id === selectedMeetingId) ?? null;
  const activeRevision = useMemo(() => activeRevisionOf(revisions), [revisions]);
  const sourceDecisions = useMemo<DecisionSource[]>(() => {
    if (!selectedMeeting || activeRevision?.format_version !== 2) return [];
    return activeRevision.discussions.flatMap((discussion) => {
      const agenda = selectedMeeting.agendas.find((item) => item.id === discussion.agenda_id);
      return discussion.decisions.map((decision) => ({
        decision,
        agendaTitle: agenda?.title ?? 'Agenda sumber',
        discussionSubject: discussion.subject,
      }));
    });
  }, [activeRevision, selectedMeeting]);

  useEffect(() => {
    let current = true;
    void getMeetings()
      .then((items) => {
        if (!current) return;
        setMeetings(items);
        setSelectedMeetingId(items[0]?.id ?? '');
      })
      .catch((error: unknown) => {
        if (current) setErrorMessage(errorMessageOf(error));
      })
      .finally(() => {
        if (current) setMeetingsLoading(false);
      });
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedMeetingId) {
      setRevisions([]);
      setHistory([]);
      return;
    }
    let current = true;
    setDataLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    void Promise.all([
      getMinutesRevisions(selectedMeetingId),
      getDecisionBriefHistory(selectedMeetingId),
    ])
      .then(([nextRevisions, nextHistory]) => {
        if (!current) return;
        setRevisions(nextRevisions);
        setHistory(nextHistory);
      })
      .catch((error: unknown) => {
        if (current) setErrorMessage(errorMessageOf(error));
      })
      .finally(() => {
        if (current) setDataLoading(false);
      });
    return () => {
      current = false;
    };
  }, [selectedMeetingId]);

  function resetDraft(): void {
    setSummary('');
    setNotes('');
    setSelectedDecisionIds(new Set());
    setPriorities({});
    setEditorialNotes({});
  }

  async function refreshSourceAndHistory(): Promise<void> {
    if (!selectedMeetingId) return;
    const [nextRevisions, nextHistory] = await Promise.all([
      getMinutesRevisions(selectedMeetingId),
      getDecisionBriefHistory(selectedMeetingId),
    ]);
    setRevisions(nextRevisions);
    setHistory(nextHistory);
  }

  function toggleDecision(decisionId: string, checked: boolean): void {
    setSelectedDecisionIds((previous) => {
      const next = new Set(previous);
      if (checked) next.add(decisionId);
      else next.delete(decisionId);
      return next;
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedMeetingId || !activeRevision || !canCreate) return;
    const selectedSources = sourceDecisions.filter(({ decision }) =>
      selectedDecisionIds.has(decision.id),
    );
    if (selectedSources.length === 0) {
      setErrorMessage('Pilih sedikitnya satu keputusan dari notulensi aktif.');
      return;
    }
    if (selectedSources.some(({ decision }) => !priorities[decision.id]?.trim())) {
      setErrorMessage('Isi prioritas editorial untuk setiap keputusan yang dipilih.');
      return;
    }

    setSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const created = await createDecisionBriefVersion(selectedMeetingId, {
        source_minutes_revision_id: activeRevision.id,
        summary: summary.trim(),
        notes: notes.trim() || null,
        decisions: selectedSources.map(({ decision }) => ({
          decision_id: decision.id,
          priority: priorities[decision.id].trim(),
          editorial_note: editorialNotes[decision.id]?.trim() || null,
        })),
      });
      setHistory((previous) => [...previous, created]);
      resetDraft();
      setPreservedDraft(null);
      setSuccessMessage(`Decision Brief versi ${created.version_number} tersimpan sebagai draf.`);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setPreservedDraft({
          sourceRevisionId: activeRevision.id,
          sourceRevisionNumber: activeRevision.revision_number,
          summary,
          notes,
          decisions: selectedSources.map(({ decision, agendaTitle, discussionSubject }) => ({
            sourceText: decision.decision_text,
            agendaTitle,
            discussionSubject,
            priority: priorities[decision.id] ?? '',
            editorialNote: editorialNotes[decision.id] ?? '',
          })),
        });
        setErrorMessage(
          'Notulensi berubah sejak sumber dimuat. Sumber terbaru dan histori brief sudah dimuat ulang; periksa keputusan lalu buat versi baru.',
        );
        try {
          await refreshSourceAndHistory();
        } catch (refreshError: unknown) {
          setErrorMessage(`${errorMessageOf(error)} ${errorMessageOf(refreshError)}`);
        }
      } else {
        setErrorMessage(errorMessageOf(error));
      }
    } finally {
      setSaving(false);
    }
  }

  if (meetingsLoading) {
    return (
      <p className="decision-brief-state" role="status">
        Memuat rapat...
      </p>
    );
  }
  if (meetings.length === 0) {
    return <p className="decision-brief-state">Tidak ada rapat yang dapat diakses.</p>;
  }

  return (
    <section className="decision-brief-page" aria-labelledby="decision-brief-title">
      <header className="decision-brief-heading">
        <div>
          <p className="eyebrow">SUMBER NOTULENSI TETAP UTUH</p>
          <h1 id="decision-brief-title">Decision Brief</h1>
          <p>
            Susun ringkasan editorial dari keputusan pada revisi notulensi aktif. Setiap penyimpanan
            menambahkan versi draf baru.
          </p>
        </div>
      </header>

      {errorMessage && (
        <p className="minutes-alert" role="alert">
          {errorMessage}
        </p>
      )}
      {successMessage && (
        <p className="minutes-notice" role="status">
          {successMessage}
        </p>
      )}

      {preservedDraft && (
        <section className="minutes-alert" aria-labelledby="preserved-brief-title">
          <h2 id="preserved-brief-title">Draf yang belum tersimpan</h2>
          <p>
            Draf ini merujuk revisi notulensi {preservedDraft.sourceRevisionNumber} (
            <code>{preservedDraft.sourceRevisionId}</code>). Draf tidak dikirim ulang; periksa
            sumber terbaru sebelum membuat versi baru.
          </p>
          <p>{preservedDraft.summary}</p>
          {preservedDraft.notes && <p>{preservedDraft.notes}</p>}
          <ul>
            {preservedDraft.decisions.map((decision, index) => (
              <li key={`${decision.sourceText}-${index}`}>
                <strong>{decision.sourceText}</strong>
                <span>
                  {decision.agendaTitle}
                  {decision.discussionSubject ? ` · ${decision.discussionSubject}` : ''}
                </span>
                <span>Prioritas: {decision.priority || 'belum diisi'}</span>
                {decision.editorialNote && <span>{decision.editorialNote}</span>}
              </li>
            ))}
          </ul>
          <button
            className="button button--secondary"
            onClick={() => setPreservedDraft(null)}
            type="button"
          >
            Tutup draf tersimpan
          </button>
        </section>
      )}

      <label className="minutes-field-label" htmlFor="decision-brief-meeting">
        Pilih rapat
      </label>
      <select
        className="minutes-select decision-brief-meeting"
        id="decision-brief-meeting"
        value={selectedMeetingId}
        onChange={(event) => {
          setSelectedMeetingId(event.target.value);
          resetDraft();
          setPreservedDraft(null);
        }}
      >
        {meetings.map((meeting) => (
          <option key={meeting.id} value={meeting.id}>
            {meeting.meeting_number} · {meeting.title}
          </option>
        ))}
      </select>

      {dataLoading ? (
        <p className="decision-brief-state" role="status">
          Memuat sumber keputusan dan histori...
        </p>
      ) : (
        <div className="decision-brief-layout">
          <div className="surface-panel decision-brief-form-panel">
            <div className="decision-brief-source">
              <h2>Sumber keputusan</h2>
              {activeRevision ? (
                <p>
                  Revisi notulensi {activeRevision.revision_number} ·{' '}
                  <code>{activeRevision.id}</code>
                </p>
              ) : (
                <p>Rapat ini belum memiliki revisi notulensi.</p>
              )}
            </div>

            {!canCreate && (
              <p className="minutes-readonly-note">
                Akun ini hanya dapat membaca histori Decision Brief.
              </p>
            )}
            {activeRevision?.format_version === 1 && (
              <p className="minutes-readonly-note">
                Revisi teks lama tetap tersedia, tetapi belum memiliki keputusan terstruktur untuk
                dipilih sebagai sumber.
              </p>
            )}
            {activeRevision?.format_version === 2 && sourceDecisions.length === 0 && (
              <p className="minutes-readonly-note">
                Revisi aktif belum mencatat keputusan terstruktur.
              </p>
            )}

            {canCreate && activeRevision?.format_version === 2 && sourceDecisions.length > 0 && (
              <form className="decision-brief-form" onSubmit={(event) => void handleSubmit(event)}>
                <label className="minutes-field-label" htmlFor="decision-brief-summary">
                  Ringkasan editorial
                </label>
                <textarea
                  className="minutes-textarea"
                  id="decision-brief-summary"
                  maxLength={100_000}
                  required
                  rows={4}
                  value={summary}
                  onChange={(event) => setSummary(event.target.value)}
                />
                <label className="minutes-field-label" htmlFor="decision-brief-notes">
                  Catatan brief (opsional)
                </label>
                <textarea
                  className="minutes-textarea"
                  id="decision-brief-notes"
                  maxLength={20_000}
                  rows={3}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                />

                <fieldset className="decision-brief-sources">
                  <legend>Pilih keputusan sumber dan isi prioritas editorial</legend>
                  {sourceDecisions.map(({ decision, agendaTitle, discussionSubject }) => (
                    <article className="decision-brief-source-card" key={decision.id}>
                      <label className="decision-brief-checkbox">
                        <input
                          checked={selectedDecisionIds.has(decision.id)}
                          onChange={(event) => toggleDecision(decision.id, event.target.checked)}
                          type="checkbox"
                        />
                        <span>{decision.decision_text}</span>
                      </label>
                      <p className="decision-brief-provenance">
                        {agendaTitle}
                        {discussionSubject ? ` · ${discussionSubject}` : ''}
                      </p>
                      {selectedDecisionIds.has(decision.id) && (
                        <div className="decision-brief-editorial-fields">
                          <label className="minutes-field-label">
                            Prioritas editorial
                            <input
                              className="minutes-input"
                              maxLength={100}
                              required
                              value={priorities[decision.id] ?? ''}
                              onChange={(event) =>
                                setPriorities((previous) => ({
                                  ...previous,
                                  [decision.id]: event.target.value,
                                }))
                              }
                            />
                          </label>
                          <label className="minutes-field-label">
                            Catatan editorial (opsional)
                            <textarea
                              className="minutes-textarea"
                              maxLength={4_000}
                              rows={2}
                              value={editorialNotes[decision.id] ?? ''}
                              onChange={(event) =>
                                setEditorialNotes((previous) => ({
                                  ...previous,
                                  [decision.id]: event.target.value,
                                }))
                              }
                            />
                          </label>
                        </div>
                      )}
                    </article>
                  ))}
                </fieldset>
                <button className="button button--primary" disabled={saving} type="submit">
                  {saving ? 'Menyimpan...' : 'Simpan versi draf'}
                </button>
              </form>
            )}
          </div>

          <aside
            className="surface-panel decision-brief-history"
            aria-labelledby="brief-history-title"
          >
            <h2 id="brief-history-title">Histori versi</h2>
            {history.length === 0 ? (
              <p className="decision-brief-state">Belum ada versi Decision Brief.</p>
            ) : (
              <ol className="decision-brief-history-list">
                {[...history].reverse().map((version) => (
                  <li className="decision-brief-version" key={version.id}>
                    <header>
                      <h3>Versi {version.version_number}</h3>
                      <span className={version.is_stale ? 'brief-stale' : 'brief-current'}>
                        {version.is_stale ? 'Sumber usang' : 'Sumber aktif'}
                      </span>
                    </header>
                    <p className="decision-brief-provenance">
                      Revisi sumber <code>{version.source_minutes_revision_id}</code>
                    </p>
                    <p className="decision-brief-history-summary">{version.summary}</p>
                    {version.notes && <p>{version.notes}</p>}
                    <ul>
                      {version.decisions.map((decision) => (
                        <li key={decision.decision_id}>
                          <strong>{decision.source_decision_text}</strong>
                          <span>
                            {decision.source_agenda_title} · Prioritas: {decision.priority}
                          </span>
                          {decision.editorial_note && <span>{decision.editorial_note}</span>}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ol>
            )}
          </aside>
        </div>
      )}
    </section>
  );
}

function errorMessageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Terjadi kesalahan saat memuat Decision Brief.';
}

export default DecisionBriefEditor;
