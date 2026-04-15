import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { DashboardMenu } from './DashboardMenu';

function renderMenu() {
  return render(
    <MemoryRouter>
      <DashboardMenu projectId="proj_1" />
    </MemoryRouter>
  );
}

describe('DashboardMenu', () => {
  it('is closed by default', () => {
    renderMenu();
    expect(screen.queryByRole('menu')).toBeNull();
    expect(screen.getByRole('button', { name: /project menu/i })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
  });

  it('opens and shows a Settings link when the hamburger is clicked', () => {
    renderMenu();
    fireEvent.click(screen.getByRole('button', { name: /project menu/i }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    const link = screen.getByRole('menuitem', { name: /settings/i });
    expect(link).toHaveAttribute('href', '/projects/proj_1/settings');
  });

  it('closes on Escape', () => {
    renderMenu();
    fireEvent.click(screen.getByRole('button', { name: /project menu/i }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('closes when clicking the Settings link', () => {
    renderMenu();
    fireEvent.click(screen.getByRole('button', { name: /project menu/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /settings/i }));
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('does not show a Vocabulary link (vocab lives in the dashboard tab)', () => {
    renderMenu();
    fireEvent.click(screen.getByRole('button', { name: /project menu/i }));
    expect(
      screen.queryByRole('menuitem', { name: /vocabulary/i })
    ).toBeNull();
  });
});
