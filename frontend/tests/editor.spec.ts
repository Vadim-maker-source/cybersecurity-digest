import {test,expect} from '@playwright/test';
test('Рабочая редакция без демонстрационных данных',async({page})=>{
 const password=process.env.E2E_EDITOR_PASSWORD;
 test.skip(!password,'Set E2E_EDITOR_PASSWORD');
 await page.goto(process.env.E2E_BASE_URL||'http://localhost:6752');
 await page.getByLabel('Email',{exact:true}).fill(process.env.E2E_EDITOR_EMAIL||'editor@localhost');
 await page.getByLabel('Пароль',{exact:true}).fill(password!);
 await page.getByRole('button',{name:'Войти',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Обзор редакции',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Загрузить демонстрацию',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Проверки',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Источники',exact:true}).click();
 await expect(page.getByRole('heading',{name:'SecurityLab',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Настройки',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Почтовая рассылка',exact:true})).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
