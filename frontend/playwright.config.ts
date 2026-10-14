import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',testMatch:'**/*.spec.ts',workers:1,
 outputDir:'../work/e2e-results',reporter:'list',use:{headless:true,trace:'off',screenshot:'only-on-failure',viewport:{width:1280,height:900}}});
