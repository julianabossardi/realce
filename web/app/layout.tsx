import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Realce — MPRJ",
  description: "Busca priorizada de documentos no acervo do MPRJ",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
