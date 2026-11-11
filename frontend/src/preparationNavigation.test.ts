import { expect, it } from 'vitest';
import { preparationGroup, preparationTabs } from './preparationNavigation';
it('maps all six existing stages to three groups without losing their tab identity', () => {
  expect(Object.keys(preparationTabs)).toHaveLength(3);
  for (const stage of ['original','memory','skeleton','outline','style','asset']) {
    expect(preparationTabs[preparationGroup(stage)].some(([id]) => id === stage)).toBe(true);
  }
});
