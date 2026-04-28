import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TierFilterChips } from './TierFilterChips';
import type { TierGroupKey } from './tierFilter';

const ALL_AVAILABLE = [
  { key: 'features' as TierGroupKey, label: 'Features' },
  { key: 'components' as TierGroupKey, label: 'Components' },
];

describe('TierFilterChips', () => {
  it('renders a chip per available group with aria-pressed reflecting visibility', () => {
    render(
      <TierFilterChips
        available={ALL_AVAILABLE}
        hidden={new Set(['features'])}
        onToggle={() => {}}
      />,
    );
    const featuresChip = screen.getByTestId('tier-filter-chip-features');
    const compsChip = screen.getByTestId('tier-filter-chip-components');
    expect(featuresChip.getAttribute('aria-pressed')).toBe('false');
    expect(compsChip.getAttribute('aria-pressed')).toBe('true');
  });

  it('clicking a chip calls onToggle with the group key', () => {
    const onToggle = vi.fn();
    render(
      <TierFilterChips
        available={ALL_AVAILABLE}
        hidden={new Set()}
        onToggle={onToggle}
      />,
    );
    fireEvent.click(screen.getByTestId('tier-filter-chip-features'));
    expect(onToggle).toHaveBeenCalledWith('features');
  });

  it('renders nothing when no groups are available', () => {
    const { container } = render(
      <TierFilterChips
        available={[]}
        hidden={new Set()}
        onToggle={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
