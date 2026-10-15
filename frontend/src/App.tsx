export default function App() {
  return (
    <main className="page-shell">
      <section className="welcome-panel" aria-labelledby="app-title">
        <p className="eyebrow">SISTEM INTERNAL</p>
        <h1 id="app-title">SITARA</h1>
        <p className="subtitle">Sistem Informasi Tindak Lanjut dan Arsip Rapat</p>
        <div className="status-line" role="status">
          <span className="status-dot" aria-hidden="true" />
          Engineering baseline siap dikembangkan
        </div>
        <p className="notice">
          Ini adalah scaffold awal. Autentikasi, hak akses, dan modul bisnis belum
          diimplementasikan.
        </p>
      </section>
    </main>
  );
}
