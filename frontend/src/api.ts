export type MeetingStatus = 'DRAFT' | 'LIVE' | 'FINAL' | 'ARCHIVED';

export interface AuthenticatedUser {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
}

export interface MeetingAgenda {
  id: string;
  agenda_number: number;
  title: string;
  agenda_description: string | null;
  sort_order: number;
}

export interface MeetingSummary {
  id: string;
  meeting_number: string;
  title: string;
  meeting_date: string;
  notetaker_id: string | null;
  status: MeetingStatus;
  agendas: MeetingAgenda[];
}

export interface MinutesDecision {
  id: string;
  discussion_id: string;
  decision_number: number;
  decision_text: string;
  output_expected: string | null;
  target_date: string | null;
  is_action_item: boolean;
}

export interface MinutesDiscussion {
  id: string;
  agenda_id: string;
  discussion_number: number;
  subject: string | null;
  content: string;
  decisions: MinutesDecision[];
}

export interface MinutesRevision {
  id: string;
  meeting_id: string;
  revision_number: number;
  format_version: 1 | 2;
  content: string | null;
  discussions: MinutesDiscussion[];
  created_by_id: string;
  created_at: string;
}

export interface DecisionBriefDecision {
  decision_id: string;
  source_decision_text: string;
  source_agenda_id: string;
  source_agenda_title: string;
  source_discussion_id: string;
  source_discussion_subject: string | null;
  priority: string;
  editorial_note: string | null;
  position: number;
}

export interface DecisionBriefVersion {
  id: string;
  meeting_id: string;
  source_minutes_revision_id: string;
  version_number: number;
  summary: string;
  notes: string | null;
  created_by_id: string;
  created_at: string;
  is_stale: boolean;
  decisions: DecisionBriefDecision[];
}

export interface DecisionBriefVersionInput {
  source_minutes_revision_id: string;
  summary: string;
  notes: string | null;
  decisions: {
    decision_id: string;
    priority: string;
    editorial_note: string | null;
  }[];
}

export interface StructuredMinutesDiscussionInput {
  agenda_id: string;
  subject: string | null;
  content: string;
  decisions: {
    decision_text: string;
    output_expected: string | null;
    target_date: string | null;
    is_action_item: boolean;
  }[];
}

export interface StructuredMinutesRevisionInput {
  format_version: 2;
  content: null;
  discussions: StructuredMinutesDiscussionInput[];
}

export function canAccessMinutes(user: AuthenticatedUser): boolean {
  const restrictedRoles = new Set(['PIC', 'SUPER_ADMIN']);
  const meetingRoles = new Set(['SEKRETARIAT', 'REKTOR', 'WAREK']);
  return (
    !user.roles.some((role) => restrictedRoles.has(role)) &&
    user.roles.some((role) => meetingRoles.has(role))
  );
}

export function canCreateDecisionBrief(user: AuthenticatedUser): boolean {
  const restrictedRoles = new Set(['PIC', 'SUPER_ADMIN']);
  const authorRoles = new Set(['SEKRETARIAT', 'REKTOR', 'WAREK']);
  return (
    !user.roles.some((role) => restrictedRoles.has(role)) &&
    user.roles.some((role) => authorRoles.has(role))
  );
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  const cookie = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  if (!cookie) return null;
  return decodeURIComponent(cookie.slice(prefix.length));
}

function validationMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'object' && item !== null && 'msg' in item) {
          return String(item.msg);
        }
        return null;
      })
      .filter((item): item is string => item !== null);
    return messages.length > 0 ? messages.join(' · ') : null;
  }
  return null;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set('Content-Type', 'application/json');

  if (init.method && init.method !== 'GET') {
    const csrfToken = readCookie('sitara_csrf');
    if (!csrfToken) {
      throw new ApiError('Token keamanan CSRF tidak tersedia. Silakan login kembali.', 403);
    }
    headers.set('X-CSRF-Token', csrfToken);
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
      credentials: 'include',
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'TimeoutError') {
      throw new ApiError('Permintaan ke server melewati batas waktu. Coba lagi.', 0);
    }
    throw new ApiError(
      'Tidak dapat terhubung ke server SITARA. Periksa koneksi lalu coba lagi.',
      0,
    );
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? validationMessage(payload.detail)
        : null;
    throw new ApiError(detail ?? `Permintaan gagal (HTTP ${response.status}).`, response.status);
  }
  return payload as T;
}

export function getCurrentUser(): Promise<AuthenticatedUser> {
  return requestJson<AuthenticatedUser>('/api/v1/auth/me');
}

export async function getMeetings(): Promise<MeetingSummary[]> {
  const allMeetings: MeetingSummary[] = [];
  const pageSize = 100;
  let offset = 0;

  while (true) {
    const page = await requestJson<MeetingSummary[]>(
      `/api/v1/meetings?limit=${pageSize}&offset=${offset}`,
    );
    allMeetings.push(...page);
    if (page.length < pageSize) return allMeetings;
    offset += page.length;
  }
}

export function getMeeting(meetingId: string): Promise<MeetingSummary> {
  return requestJson<MeetingSummary>(`/api/v1/meetings/${encodeURIComponent(meetingId)}`);
}

export function getMinutesRevisions(meetingId: string): Promise<MinutesRevision[]> {
  return requestJson<MinutesRevision[]>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/minutes-revisions`,
  );
}

export function createMinutesRevision(
  meetingId: string,
  snapshot: string | StructuredMinutesRevisionInput,
  baseRevisionId: string | null,
): Promise<MinutesRevision> {
  const body =
    typeof snapshot === 'string'
      ? { content: snapshot, base_revision_id: baseRevisionId }
      : { ...snapshot, base_revision_id: baseRevisionId };
  return requestJson<MinutesRevision>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/minutes-revisions`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  );
}

export function getDecisionBriefHistory(meetingId: string): Promise<DecisionBriefVersion[]> {
  return requestJson<DecisionBriefVersion[]>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs`,
  );
}

export function createDecisionBriefVersion(
  meetingId: string,
  input: DecisionBriefVersionInput,
): Promise<DecisionBriefVersion> {
  return requestJson<DecisionBriefVersion>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs`,
    { method: 'POST', body: JSON.stringify(input) },
  );
}
