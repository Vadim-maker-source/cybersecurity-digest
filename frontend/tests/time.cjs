const {test}=require('node:test');
const assert=require('node:assert/strict');
const {moscowMinute,pastDailyPeriod}=require('../lib/time.ts');

test('Moscow date crosses month and year independently of browser timezone',()=>{
 assert.equal(moscowMinute(new Date('2026-10-31T22:05:00Z')),'2026-11-01T01:05');
 assert.equal(moscowMinute(new Date('2026-12-31T21:00:00Z')),'2027-01-01T00:00');
});

test('Historical control time stays unchanged while the current clock advances',()=>{
 const control='2026-10-28T20:00:00+03:00';
 assert.equal(pastDailyPeriod(control,'2026-10-29T20:00:00+03:00'),false);
 assert.equal(pastDailyPeriod(control,'2026-10-29T20:00:01+03:00'),true);
 assert.equal(control,'2026-10-28T20:00:00+03:00');
});
