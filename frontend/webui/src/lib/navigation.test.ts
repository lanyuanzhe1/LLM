import { describe, expect, it } from 'vitest';

import { navItems } from './navigation';

describe('main navigation', () => {
	it('sends the agent plaza through a full-page request while keeping local routes client-side', () => {
		expect(navItems.find((item) => item.href === '/agents')).toMatchObject({ fullReload: true });
		expect(navItems.filter((item) => item.href !== '/agents').every((item) => !item.fullReload)).toBe(true);
	});
});
