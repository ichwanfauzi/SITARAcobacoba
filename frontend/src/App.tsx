import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { canAccessMinutes, getCurrentUser, type AuthenticatedUser } from './api';
import DecisionBriefEditor from './DecisionBriefEditor';
import MinutesEditor, { UNSAVED_MINUTES_NAVIGATION_WARNING } from './MinutesEditor';

type IconName =
  | 'grid'
  | 'calendar'
  | 'checklist'
  | 'chart'
  | 'search'
  | 'bell'
  | 'arrow'
  | 'clock'
  | 'users'
  | 'chevron'
  | 'close'
  | 'document';
type TaskStatus = 'BELUM_DIMULAI' | 'BERPROSES' | 'TERKENDALA' | 'MENUNGGU_ACC' | 'SELESAI';

type Meeting = {
  date: string;
  title: string;
  participants: number;
  status: 'FINAL' | 'DRAF';
};

type FollowUp = {
  title: string;
  owner: string;
  unit: string;
  due: string;
  status: TaskStatus;
  overdue: boolean;
};

const iconPaths: Record<IconName, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z',
  calendar: 'M7 2v4 M17 2v4 M3 9h18 M5 4h14a2 2 0 0 1 2 2v13H3V6a2 2 0 0 1 2-2z',
  checklist: 'M9 6h11 M9 12h11 M9 18h11 M4 6l1 1 2-2 M4 12l1 1 2-2 M4 18l1 1 2-2',
  chart: 'M4 19V5 M4 19h17 M8 15l4-4 3 2 5-6',
  search: 'm20 20-4.5-4.5 M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0z',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 6v6l4 2',
  users:
    'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M20 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75',
  chevron: 'm9 18 6-6-6-6',
  close: 'm18 6-12 12 M6 6l12 12',
  document: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8',
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={iconPaths[name]} />
    </svg>
  );
}

const demoMeetings: Meeting[] = [
  {
    date: '02 Okt 2026',
    title: 'Evaluasi kinerja dan tindak lanjut triwulan',
    participants: 12,
    status: 'FINAL',
  },
  {
    date: '29 Sep 2026',
    title: 'Koordinasi program kemitraan industri',
    participants: 9,
    status: 'FINAL',
  },
  {
    date: '18 Sep 2026',
    title: 'Pembahasan rencana kerja semester genap',
    participants: 11,
    status: 'DRAF',
  },
  {
    date: '10 Sep 2026',
    title: 'Pemantauan capaian program strategis',
    participants: 8,
    status: 'FINAL',
  },
];

const demoFollowUps: FollowUp[] = [
  {
    title: 'Evaluasi tindak lanjut kerja sama industri',
    owner: 'Dr. Raka Pratama',
    unit: 'Wakil Rektor IV',
    due: '10 Okt 2026',
    status: 'TERKENDALA',
    overdue: true,
  },
  {
    title: 'Penataan arsip keputusan semester genap',
    owner: 'Nadia Putri',
    unit: 'Sekretariat',
    due: '17 Okt 2026',
    status: 'BERPROSES',
    overdue: false,
  },
  {
    title: 'Penyusunan bahan rapat evaluasi akademik',
    owner: 'M. Farhan',
    unit: 'Wakil Rektor I',
    due: '16 Okt 2026',
    status: 'MENUNGGU_ACC',
    overdue: false,
  },
  {
    title: 'Rekap progres implementasi program prioritas',
    owner: 'Sinta Maharani',
    unit: 'Biro Perencanaan',
    due: '12 Okt 2026',
    status: 'BELUM_DIMULAI',
    overdue: true,
  },
  {
    title: 'Validasi daftar PIC kegiatan institusi',
    owner: 'Ari Wibowo',
    unit: 'Sekretariat',
    due: '08 Okt 2026',
    status: 'SELESAI',
    overdue: false,
  },
  {
    title: 'Pembaruan matriks tindak lanjut Rapim',
    owner: 'Dewi Lestari',
    unit: 'Sekretariat',
    due: '20 Okt 2026',
    status: 'BERPROSES',
    overdue: false,
  },
];

const demoDecisionTitles = [
  'Evaluasi kerja sama industri',
  'Rencana kerja semester genap',
  'Capaian program strategis',
  'Penguatan layanan akademik',
  'Evaluasi tindak lanjut unit',
  'Penataan arsip rapat',
  'Koordinasi agenda institusi',
  'Pemantauan program prioritas',
];

const statusLabels: Record<TaskStatus, string> = {
  BELUM_DIMULAI: 'Belum dimulai',
  BERPROSES: 'Berproses',
  TERKENDALA: 'Terkendala',
  MENUNGGU_ACC: 'Menunggu Acc',
  SELESAI: 'Selesai',
};
const statusOrder: TaskStatus[] = [
  'BELUM_DIMULAI',
  'BERPROSES',
  'TERKENDALA',
  'MENUNGGU_ACC',
  'SELESAI',
];

function App() {
  const [query, setQuery] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [authenticatedUser, setAuthenticatedUser] = useState<AuthenticatedUser | null>(null);
  const [authStatus, setAuthStatus] = useState<'loading' | 'authenticated' | 'anonymous'>(
    'loading',
  );
  const [activeView, setActiveView] = useState<'dashboard' | 'minutes' | 'decision-briefs'>(() => {
    if (window.location.hash === '#notulensi') return 'minutes';
    if (window.location.hash === '#decision-briefs') return 'decision-briefs';
    return 'dashboard';
  });
  const [minutesHasPendingDraft, setMinutesHasPendingDraft] = useState(false);
  const previousHashRef = useRef(window.location.hash || '#dashboard');
  const approvedHashRef = useRef<string | null>(null);
  useEffect(() => {
    const syncViewFromHash = () => {
      const nextHash = window.location.hash || '#dashboard';
      if (approvedHashRef.current === nextHash) {
        approvedHashRef.current = null;
      } else if (
        minutesHasPendingDraft &&
        nextHash !== previousHashRef.current &&
        !window.confirm(UNSAVED_MINUTES_NAVIGATION_WARNING)
      ) {
        window.history.replaceState(null, '', previousHashRef.current);
        return;
      }
      previousHashRef.current = nextHash;
      setActiveView(
        nextHash === '#notulensi'
          ? 'minutes'
          : nextHash === '#decision-briefs'
            ? 'decision-briefs'
            : 'dashboard',
      );
    };
    window.addEventListener('hashchange', syncViewFromHash);
    return () => window.removeEventListener('hashchange', syncViewFromHash);
  }, [minutesHasPendingDraft]);
  useEffect(() => {
    if (!minutesHasPendingDraft) return;
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', preventUnload);
    return () => window.removeEventListener('beforeunload', preventUnload);
  }, [minutesHasPendingDraft]);
  useEffect(() => {
    let mounted = true;
    void getCurrentUser()
      .then((user) => {
        if (mounted) {
          setAuthenticatedUser(user);
          setAuthStatus('authenticated');
        }
      })
      .catch(() => {
        if (mounted) {
          setAuthenticatedUser(null);
          setAuthStatus('anonymous');
        }
      });
    return () => {
      mounted = false;
    };
  }, []);
  const canOpenMinutes = authenticatedUser ? canAccessMinutes(authenticatedUser) : false;
  function guardUnsavedMinutesNavigation(event: ReactMouseEvent<HTMLDivElement>): void {
    if (!minutesHasPendingDraft || !(event.target instanceof Element)) return;
    const link = event.target.closest<HTMLAnchorElement>('a[href^="#"]');
    const targetHash = link?.hash;
    if (!targetHash || targetHash === (window.location.hash || '#dashboard')) return;
    if (!window.confirm(UNSAVED_MINUTES_NAVIGATION_WARNING)) {
      event.preventDefault();
      return;
    }
    approvedHashRef.current = targetHash;
  }
  const normalizedQuery = query.trim().toLocaleLowerCase('id');
  const visibleMeetings = demoMeetings.filter((meeting) =>
    meeting.title.toLocaleLowerCase('id').includes(normalizedQuery),
  );
  const visibleFollowUps = demoFollowUps.filter((task) =>
    [task.title, task.owner, task.unit, statusLabels[task.status]]
      .join(' ')
      .toLocaleLowerCase('id')
      .includes(normalizedQuery),
  );
  const overdueCount = demoFollowUps.filter((task) => task.overdue).length;
  const statusCounts = statusOrder.map((status) => ({
    status,
    count: demoFollowUps.filter((task) => task.status === status).length,
  }));

  return (
    <div className="app-shell" onClickCapture={guardUnsavedMinutesNavigation}>
      <aside className="sidebar">
        <a className="brand" href="#dashboard" aria-label="SITARA, ke dashboard">
          <span className="brand-mark">S</span>
          <span className="brand-copy">
            <strong>SITARA</strong>
            <small>Sistem Informasi Tindak Lanjut dan Arsip Rapat</small>
          </span>
        </a>
        <div className="workspace-label">RUANG KERJA</div>
        <nav className="primary-nav" aria-label="Navigasi utama">
          <a
            className={`nav-link${activeView === 'dashboard' ? ' is-active' : ''}`}
            href="#dashboard"
            aria-current={activeView === 'dashboard' ? 'page' : undefined}
          >
            <Icon name="grid" />
            <span>Dashboard</span>
          </a>
          <a className="nav-link" href="#rapat-terbaru">
            <Icon name="calendar" />
            <span>Rapat</span>
            <span className="nav-count">04</span>
          </a>
          {canOpenMinutes && (
            <a
              className={`nav-link${activeView === 'minutes' ? ' is-active' : ''}`}
              href="#notulensi"
              aria-current={activeView === 'minutes' ? 'page' : undefined}
            >
              <Icon name="document" />
              <span>Notulensi</span>
            </a>
          )}
          {canOpenMinutes && (
            <a
              className={`nav-link${activeView === 'decision-briefs' ? ' is-active' : ''}`}
              href="#decision-briefs"
              aria-current={activeView === 'decision-briefs' ? 'page' : undefined}
            >
              <Icon name="chart" />
              <span>Decision Brief</span>
            </a>
          )}
          <a className="nav-link" href="#prioritas">
            <Icon name="checklist" />
            <span>Tindak lanjut</span>
            <span className="nav-count nav-count--alert">02</span>
          </a>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-divider" />
        <div className="profile-summary">
          <div className="avatar" aria-hidden="true">
            SR
          </div>
          <div className="profile-copy">
            <strong>Sekretariat Rapim</strong>
            <span>Administrator</span>
          </div>
        </div>
      </aside>

      <main className="main-content" id="dashboard">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Ruang kerja</span>
            <Icon name="chevron" size={14} />
            <strong>
              {activeView === 'minutes'
                ? 'Notulensi'
                : activeView === 'decision-briefs'
                  ? 'Decision Brief'
                  : 'Dashboard'}
            </strong>
          </div>
          <div className="topbar-actions">
            <label className="search-field">
              <Icon name="search" size={17} />
              <input
                type="search"
                aria-label="Cari rapat atau tindak lanjut"
                placeholder="Cari rapat atau tindak lanjut"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              {query && (
                <button
                  className="clear-search"
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="Hapus pencarian"
                >
                  <Icon name="close" size={15} />
                </button>
              )}
            </label>
            <div className="notification-wrap">
              <button
                className={`icon-button${notificationsOpen ? ' is-pressed' : ''}`}
                type="button"
                aria-label="Notifikasi"
                aria-expanded={notificationsOpen}
                onClick={() => setNotificationsOpen((open) => !open)}
              >
                <Icon name="bell" />
                <span className="notification-dot" aria-hidden="true" />
              </button>
              {notificationsOpen && (
                <div className="notification-popover" role="status">
                  <strong>Notifikasi demo</strong>
                  <p>2 tindak lanjut perlu diperhatikan.</p>
                  <a href="#prioritas" onClick={() => setNotificationsOpen(false)}>
                    Lihat daftar <Icon name="arrow" size={15} />
                  </a>
                </div>
              )}
            </div>
            <div className="topbar-profile" aria-label="Profil Sekretariat">
              <div className="avatar avatar--small" aria-hidden="true">
                SR
              </div>
              <span>Sekretariat</span>
            </div>
          </div>
        </header>

        {activeView === 'minutes' && (
          <div className="dashboard-content">
            {authStatus === 'loading' ? (
              <p role="status">Memeriksa sesi dan hak akses…</p>
            ) : authenticatedUser ? (
              <MinutesEditor
                authenticatedUser={authenticatedUser}
                onPendingDraftChange={setMinutesHasPendingDraft}
              />
            ) : (
              <p className="minutes-alert" role="alert">
                Sesi tidak aktif. Silakan login kembali lalu buka editor.
              </p>
            )}
          </div>
        )}
        {activeView === 'decision-briefs' && (
          <div className="dashboard-content">
            {authStatus === 'loading' ? (
              <p role="status">Memeriksa sesi dan hak akses...</p>
            ) : authenticatedUser && canOpenMinutes ? (
              <DecisionBriefEditor authenticatedUser={authenticatedUser} />
            ) : (
              <p className="minutes-alert" role="alert">
                Sesi tidak aktif atau Anda tidak berwenang membuka Decision Brief.
              </p>
            )}
          </div>
        )}
        <div className="dashboard-content" hidden={activeView !== 'dashboard'}>
          <section className="page-heading" aria-labelledby="page-title">
            <div>
              <p className="eyebrow">KAMIS, 15 OKTOBER 2026</p>
              <h1 id="page-title">Ringkasan operasional</h1>
              <p className="page-description">
                Pantau rapat, keputusan, dan tindak lanjut dalam satu ruang kerja.
              </p>
            </div>
            <a className="text-action" href="#rapat-terbaru">
              Lihat aktivitas <Icon name="arrow" size={16} />
            </a>
          </section>

          <div className="demo-notice" role="note">
            <span className="demo-notice-mark" aria-hidden="true">
              i
            </span>
            <span>
              <strong>Data contoh</strong> untuk pratinjau dashboard. Belum terhubung ke database
              atau API.
            </span>
          </div>

          <section className="metric-grid" aria-label="Ringkasan data contoh">
            <Metric
              label="Rapat tahun ini"
              value={demoMeetings.length}
              detail="4 rapat terbaru ditampilkan"
              tone="blue"
              icon="calendar"
            />
            <Metric
              label="Total keputusan"
              value={demoDecisionTitles.length}
              detail="Terhubung dengan agenda rapat"
              tone="green"
              icon="checklist"
            />
            <Metric
              label="Action items"
              value={demoFollowUps.length}
              detail="Dalam sampel tindak lanjut"
              tone="violet"
              icon="chart"
            />
            <Metric
              label="Tugas terlambat"
              value={overdueCount}
              detail="Perlu ditinjau Sekretariat"
              tone="red"
              icon="clock"
            />
          </section>

          <div className="overview-grid">
            <section
              className="surface-panel progress-panel"
              id="ringkasan-progres"
              aria-labelledby="progress-title"
            >
              <div className="section-heading">
                <div>
                  <p className="section-kicker">MONITORING</p>
                  <h2 id="progress-title">Progres tindak lanjut</h2>
                </div>
                <span className="period-label">Sampel saat ini</span>
              </div>
              <div className="progress-summary">
                <div className="progress-total">
                  <strong>{demoFollowUps.length}</strong>
                  <span>
                    action items
                    <br />
                    dalam data contoh
                  </span>
                </div>
                <div className="status-breakdown">
                  {statusCounts.map(({ status, count }) => (
                    <div className="status-row" key={status}>
                      <span
                        className={`status-dot status-dot--${status.toLowerCase()}`}
                        aria-hidden="true"
                      />
                      <span className="status-row-label">{statusLabels[status]}</span>
                      <div className="status-track" aria-hidden="true">
                        <span
                          className={`status-fill status-fill--${status.toLowerCase()}`}
                          style={{ width: `${(count / demoFollowUps.length) * 100}%` }}
                        />
                      </div>
                      <strong className="status-row-count">{count}</strong>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="attention-panel" id="prioritas" aria-labelledby="attention-title">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">TINDAKAN</p>
                  <h2 id="attention-title">Perlu perhatian</h2>
                </div>
                <span className="attention-count">{overdueCount.toString().padStart(2, '0')}</span>
              </div>
              <p className="attention-copy">
                Tenggat terlewati atau status membutuhkan tindak lanjut.
              </p>
              <div className="attention-list">
                {demoFollowUps
                  .filter(
                    (task) =>
                      task.overdue ||
                      task.status === 'TERKENDALA' ||
                      task.status === 'MENUNGGU_ACC',
                  )
                  .slice(0, 3)
                  .map((task) => (
                    <div className="attention-item" key={task.title}>
                      <span
                        className={`attention-indicator${task.overdue ? ' is-overdue' : ''}`}
                        aria-hidden="true"
                      />
                      <div className="attention-item-copy">
                        <strong>{task.title}</strong>
                        <span>
                          {task.overdue
                            ? `Lewat tenggat · ${task.due}`
                            : `${statusLabels[task.status]} · ${task.due}`}
                        </span>
                      </div>
                      <Icon name="chevron" size={16} />
                    </div>
                  ))}
              </div>
              <a className="panel-link" href="#prioritas">
                Buka tindak lanjut <Icon name="arrow" size={15} />
              </a>
            </section>
          </div>

          <div className="detail-grid">
            <section
              className="surface-panel meetings-panel"
              id="rapat-terbaru"
              aria-labelledby="meetings-title"
            >
              <div className="section-heading">
                <div>
                  <p className="section-kicker">AGENDA &amp; NOTULENSI</p>
                  <h2 id="meetings-title">Rapat terbaru</h2>
                </div>
                <a className="small-link" href="#rapat-terbaru">
                  Semua rapat <Icon name="arrow" size={15} />
                </a>
              </div>
              <div className="meeting-table-wrap">
                <table className="meeting-table">
                  <thead>
                    <tr>
                      <th scope="col">RAPAT</th>
                      <th scope="col">PESERTA</th>
                      <th scope="col">STATUS</th>
                      <th scope="col" aria-label="Aksi" />
                    </tr>
                  </thead>
                  <tbody>
                    {visibleMeetings.map((meeting) => (
                      <tr key={meeting.title}>
                        <td>
                          <div className="meeting-title">{meeting.title}</div>
                          <div className="meeting-date">{meeting.date}</div>
                        </td>
                        <td>
                          <span className="participant-count">
                            <Icon name="users" size={15} />
                            {meeting.participants}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`meeting-status meeting-status--${meeting.status.toLowerCase()}`}
                          >
                            {meeting.status === 'FINAL' ? 'Final' : 'Draf'}
                          </span>
                        </td>
                        <td>
                          <a
                            className="row-action"
                            href="#rapat-terbaru"
                            aria-label={`Buka ${meeting.title}`}
                          >
                            <Icon name="chevron" size={17} />
                          </a>
                        </td>
                      </tr>
                    ))}
                    {visibleMeetings.length === 0 && (
                      <tr>
                        <td className="empty-result" colSpan={4}>
                          Tidak ada rapat yang cocok dengan pencarian.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section
              className="surface-panel followups-panel"
              aria-label="Tindak lanjut perlu perhatian"
            >
              <div className="section-heading">
                <div>
                  <p className="section-kicker">PEMANTAUAN PIC</p>
                  <h2>Daftar tindak lanjut</h2>
                </div>
                <a className="row-action" href="#prioritas" aria-label="Lihat bagian tindak lanjut">
                  <Icon name="arrow" size={16} />
                </a>
              </div>
              <div className="followup-list">
                {visibleFollowUps
                  .filter((task) => task.status !== 'SELESAI')
                  .map((task) => (
                    <article className="followup-item" key={task.title}>
                      <div className="followup-topline">
                        <span className={`status-pill status-pill--${task.status.toLowerCase()}`}>
                          {statusLabels[task.status]}
                        </span>
                        {task.overdue && <span className="overdue-label">Terlambat</span>}
                      </div>
                      <h3>{task.title}</h3>
                      <div className="followup-meta">
                        <span>{task.owner}</span>
                        <span className="meta-divider" aria-hidden="true">
                          ·
                        </span>
                        <span>{task.unit}</span>
                      </div>
                      <div className="due-line">
                        <Icon name="clock" size={14} />
                        <span>Target {task.due}</span>
                      </div>
                    </article>
                  ))}
                {visibleFollowUps.filter((task) => task.status !== 'SELESAI').length === 0 && (
                  <p className="empty-result">
                    Tidak ada tindak lanjut yang cocok dengan pencarian.
                  </p>
                )}
              </div>
            </section>
          </div>
          <footer className="dashboard-footer">
            <span>Pratinjau dashboard SITARA</span>
            <span>Angka dan nama dalam halaman ini adalah data sintetis.</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  tone,
  icon,
}: {
  label: string;
  value: number;
  detail: string;
  tone: 'blue' | 'green' | 'violet' | 'red';
  icon: IconName;
}) {
  return (
    <article className="metric-item">
      <div className="metric-topline">
        <span className="metric-label">{label}</span>
        <span className={`metric-icon metric-icon--${tone}`}>
          <Icon name={icon} size={17} />
        </span>
      </div>
      <strong className="metric-value">{value.toString().padStart(2, '0')}</strong>
      <span className="metric-detail">{detail}</span>
    </article>
  );
}

export default App;
