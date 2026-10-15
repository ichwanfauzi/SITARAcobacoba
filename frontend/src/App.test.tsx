import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('SITARA landing scaffold', () => {
  it('shows the product name and purpose', () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: 'SITARA' })).toBeInTheDocument();
    expect(screen.getByText('Sistem Informasi Tindak Lanjut dan Arsip Rapat')).toBeInTheDocument();
  });

  it('clearly discloses that business features are not implemented yet', () => {
    render(<App />);

    expect(
      screen.getByText(/Autentikasi, hak akses, dan modul bisnis belum diimplementasikan/i),
    ).toBeInTheDocument();
  });
});
