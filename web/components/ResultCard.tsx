"use client";

import { TagList } from "@/components/TagList";
import { resumoDe } from "@/lib/resumo";
import { tagsDoResultado } from "@/lib/tags";
import type { ResultadoBusca } from "@/lib/types";

export function scoreTier(r: ResultadoBusca): { label: string; bg: string; color: string } {
  const s = r.score_criterios ?? 0;
  if (s >= 0.7) return { label: "Alta relevância", bg: "var(--priority-high-bg)", color: "var(--priority-high)" };
  if (s >= 0.35) return { label: "Média relevância", bg: "var(--priority-medium-bg)", color: "var(--priority-medium)" };
  // Nenhum critério de priorização "bateu" (score 0) não é o mesmo que "sem
  // relevância" - o resultado ainda pode ter sido encontrado pelos dois
  // caminhos de busca (léxico + vetorial concordando), sinal genuíno de
  // confiança da busca híbrida mesmo sem atender a um critério específico.
  // Sem isso, a distribuição de score por critério fica quase binária (0 ou
  // ~1) e quase tudo cai em "baixa relevância", escondendo o que a busca já
  // acertou.
  if ((r.encontrado_em?.length ?? 0) >= 2) {
    return { label: "Média relevância", bg: "var(--priority-medium-bg)", color: "var(--priority-medium)" };
  }
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
  // titulo do documento (gerado na ingestao por LLM, uma vez por documento -
  // nao mais um corte cru do chunk); resumoDe so entra como fallback para
  // dados ingeridos antes dessa camada existir, ou se a geracao falhou.
  const titulo = r.titulo || resumoDe(r.texto);
  // tags no lugar de um pedaco cru do trecho: um recorte de texto fora de
  // contexto, mal formatado e representando so parte do material nao
  // ajudava o analista a decidir se vale abrir o card - os criterios
  // atendidos (e o metodo de extracao, quando OCR) complementam melhor o
  // titulo (ver README, Revisao 4 - ajustes pos-demo).
  const tags = tagsDoResultado(r);

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
          <div style={{ fontSize: 12.5, color: "var(--text-tertiary)", marginTop: 4 }}>
            {r.municipio} · {r.data_publicacao}
            {r.pagina ? ` · p. ${r.pagina}` : ""}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <TagList tags={tags} />
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
              flexShrink: 0,
            }}
          >
            {isSaved ? "Remover do dossiê" : "Salvar no dossiê"}
          </button>
        </div>
      </div>
    </div>
  );
}
