import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata={title:'КиберСводка · Дайджест по кибербезопасности',description:'Дайджест по кибербезопасности с проверяемыми фактами и источниками'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="ru"><body>{children}</body></html>}
