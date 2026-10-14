const {test}=require('node:test');
const assert=require('node:assert/strict');
const {countCharacters,renderPlain}=require('../lib/characters.ts');
test('Code points, whitespace and only registered URLs',()=>{
 const url='https://fixture.invalid/a';
 assert.equal(countCharacters('я😀 \n'+url,[url]),4);
 assert.equal(countCharacters(url+' '+url,[url]),1);
 assert.equal(countCharacters('https://other.invalid/a',[url]),23);
 assert.equal(countCharacters('а'.repeat(4001),[]),4001);
 assert.equal(countCharacters(url+'-another',[url]),(url+'-another').length);
});
test('Visible source label counted, href excluded',()=>{
 const text='Источник\nhttps://fixture.invalid/a';
 assert.equal(countCharacters(text,['https://fixture.invalid/a']),9);
});
