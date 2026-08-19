"use client";

import { rotuloCriterio } from "@/lib/criterios";
import { resumoDe } from "@/lib/resumo";
import type { ResultadoBusca } from "@/lib/types";

export function scoreTier(r: ResultadoBusca): { label: string; bg: string; color: string } {
  const s = r.score_criterios ?? 0;
  if (s >= 0.7) return { label: "Alta relevância", bg: "var(--priority-high-bg)", color: "var(--priority-high)" };
  if (s >= 0.35) return { label: "Média relevância", bg: "var(--priority-medium-bg)", color: "var(--priority-medium)" };
  return { label: "Baixa relevância", bg: "var(--priority-low-bg)", color: "var(--priority-low)" };
}

export function ResultCard({
  r,
  isSaved,
  onOpenDetail,
  onToggleSave,
  opacity = 1,
}: {
  r: ResultadoBusca;
  isSaved: boolean;
  onOpenDetail: () => void;
  onToggleSave: () => void;
  opacity?: number;
}) {
  const tier = scoreTier(r);
  const criteriosAtendidos = r.avaliacoes.filter((a) => a.atende).slice(0, 2);
  // titulo do documento (gerado na ingestao por LLM, uma vez por documento -
  // nao mais um corte cru do chunk); resumoDe so entra como fallback para
  // dados ingeridos antes dessa camada existir, ou se a geracao falhou.
  const titulo = r.titulo || resumoDe(r.texto);

  return (
    <div
      onClick={onOpenDetail}
      style={{
        background: "var(--neutral-0)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-sm)",
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        cursor: "pointer",
        opacity,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          style={{
            alignSelf: "flex-start",
            background: tier.bg,
            color: tier.color,
            fontSize: 12,
            fontWeight: 600,
            padding: "3px 10px",
            borderRadius: "var(--radius-pill)",
          }}
        >
          {tier.label}
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)", lineHeight: 1.4 }}>
            {titulo}
          </div>
          <div
            style={{
              fontSize: 13,
              color: "var(--text-secondary)",
              marginTop: 4,
              lineHeight: 1.5,
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {r.texto}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-tertiary)", marginTop: 4 }}>
            {r.municipio} · {r.data_publicacao}
            {r.pagina ? ` · p. ${r.pagina}` : ""}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {criteriosAtendidos.map((c) => (
            <span
              key={c.criterio_id}
              style={{
                background: "var(--neutral-100)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                padding: "3px 9px",
                fontSize: 12,
                color: "var(--text-primary)",
              }}
            >
              {rotuloCriterio(c.criterio_chave)}
            </span>
          ))}
        </div>
        <div onClick={(e) => e.stopPropagation()}>
          <button
            onClick={onToggleSave}
            style={{
              padding: "6px 12px",
              fontSize: 13,
              fontWeight: 600,
              borderRadius: "var(--radius-sm)",
              border: isSaved ? "1px solid var(--border-default)" : "none",
              background: isSaved ? "var(--neutral-0)" : "var(--orange-600)",
              color: isSaved ? "var(--text-primary)" : "#fff",
              cursor: "pointer",
            }}
          >
            {isSaved ? "Remover do dossiê" : "Salvar no dossiê"}
          </button>
        </div>
      </div>
    </div>
  );
}
