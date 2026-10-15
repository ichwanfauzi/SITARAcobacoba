import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('SITARA dashboard', () => {
  it('shows the product identity, navigation, and operational summaries', () => {
    render(<App />);

    expect(screen.getByRole('link', { name: 'SITARA, ke dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Sistem Informasi Tindak Lanjut dan Arsip Rapat')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Ringkasan operasional' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Navigasi utama' })).toBeInTheDocument();
    expect(screen.getByText('Data contoh')).toBeInTheDocument();
    expect(screen.getByText('Rapat tahun ini')).toBeInTheDocument();
    expect(screen.getByText('Keputusan')).toBeInTheDocument();
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
});
