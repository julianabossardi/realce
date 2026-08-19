"use client";

import { Lock } from "lucide-react";
import type { ReactNode } from "react";

const PSEUDONIMO_RE = /\[[A-Z]+_[A-Z]+\]/g;

/**
 * O backend desmascara o chunk inteiro quando o perfil tem clearance, ou
 * devolve os pseudonimos literais ([PESSOA_A], [CPF_A], ...) quando nao
 * tem. Esta funcao so cuida da apresentacao visual: destaca os
 * pseudonimos restantes como "dado protegido" quando ainda aparecem no
 * texto (perfil sem clearance).
 */
export function renderTextoComMascara(texto: string): ReactNode[] {
  const partes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(PSEUDONIMO_RE);
  let idx = 0;
  while ((match = re.exec(texto))) {
    if (match.index > cursor) partes.push(texto.slice(cursor, match.index));
    partes.push(
      <span
        key={`mask-${idx++}`}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          background: "var(--neutral-200)",
          color: "var(--text-secondary)",
          padding: "2px 8px",
          borderRadius: "var(--radius-sm)",
          fontSize: "0.95em",
        }}
      >
        <Lock size={12} />
        dado protegido
      </span>
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < texto.length) partes.push(texto.slice(cursor));
  return partes;
}
