"use client";

import { BookmarkCheck, ChevronDown, ChevronUp, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useState } from "react";
import { renderTextoComMascara } from "@/lib/mask";
import { resumoDe } from "@/lib/resumo";
import type { ResultadoBusca } from "@/lib/types";

export function DetailPanel({
  r,
  isSaved,
  relevancia,
  onClose,
  onToggleSave,
  onSetRelevancia,
  onOpenFullDoc,
}: {
  r: ResultadoBusca;
  isSaved: boolean;
  relevancia: boolean | null;
  onClose: () => void;
  onToggleSave: () => void;
  onSetRelevancia: (v: boolean | null) => void;
  onOpenFullDoc: () => void;
}) {
  const [rastreabilidadeOpen, setRastreabilidadeOpen] = useState(false);
  const title = resumoDe(r.texto);

  return (
    <div
      style={{
        width: 380,
        flexShrink: 0,
        borderLeft: "1px solid var(--border-subtle)",
        background: "var(--neutral-0)",
        height: "100%",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "20px 24px",
          borderBottom: "1px solid var(--border-subtle)",
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            {r.arquivo_local} · {r.data_publicacao}
            {r.pagina ? ` · p. ${r.pagina}` : ""}
          </div>
          <div
            style={{
              fontFamily: "var(--font-display)",
              fontWeight: 700,
              fontSize: 16,
              lineHeight: 1.4,
              marginTop: 4,
              color: "var(--text-primary)",
            }}
          >
            {title}
          </div>
          {isSaved && (
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                background: "var(--status-success-bg)",
                color: "var(--status-success)",
                padding: "3px 10px",
                borderRadius: "var(--radius-pill)",
                fontSize: 12,
                fontWeight: 600,
                marginTop: 8,
              }}
            >
              <BookmarkCheck size={12} />
              Salvo no dossiê deste caso
            </div>
          )}
        </div>
        <button onClick={onClose} aria-label="Fechar" style={iconButtonStyle}>
          <X size={16} />
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 22 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-tertiary)", marginBottom: 8 }}>
            Trecho no contexto
          </div>
          <div
            style={{
              fontSize: 15,
              lineHeight: 1.7,
              color: "var(--text-primary)",
              background: "var(--surface-sunken)",
              padding: 14,
              borderRadius: "var(--radius-md)",
              whiteSpace: "pre-wrap",
            }}
          >
            {renderTextoComMascara(r.texto)}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-tertiary)", marginBottom: 8 }}>
            Critérios e justificativa
          </div>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginBottom: 8 }}>
            Avaliação da ferramenta — a decisão final é do analista.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {r.avaliacoes.map((c) => (
              <div
                key={c.criterio_id}
                style={{ border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: "10px 12px" }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 3 }}>
                  {c.criterio_chave} {c.atende ? "✓" : "—"}
                  {!c.citacao_verificada && c.trecho_citado ? (
                    <span title="Citação não confirmada literalmente no texto" style={{ color: "var(--status-warning)" }}>
                      {" "}
                      ⚠️
                    </span>
                  ) : null}
                </div>
                <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>{c.justificativa}</div>
              </div>
            ))}
            {r.avaliacoes.length === 0 && (
              <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>Nenhuma avaliação disponível.</div>
            )}
          </div>
        </div>

        <div>
          <button
            onClick={() => setRastreabilidadeOpen((v) => !v)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              background: "none",
              border: "none",
              color: "var(--text-secondary)",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              padding: 0,
            }}
          >
            {rastreabilidadeOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            Rastreabilidade
          </button>
          {rastreabilidadeOpen && (
            <div
              style={{
                marginTop: 10,
                display: "flex",
                flexDirection: "column",
                gap: 8,
                fontSize: 13,
                background: "var(--surface-sunken)",
                borderRadius: "var(--radius-md)",
                padding: "12px 14px",
              }}
            >
              <Row label="Documento de origem" value={r.arquivo_local} />
              <Row label="Página" value={r.pagina ? String(r.pagina) : "—"} />
              <Row label="Método de extração" value={r.metodo_extracao} />
              <Row label="Modelo de avaliação" value="qwen2.5:7b-instruct (Ollama, local)" />
              <Row label="Fonte original" value={<a href={r.url_origem} target="_blank" rel="noreferrer">abrir</a>} />
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          padding: "16px 24px",
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div style={{ display: "flex", gap: 4 }}>
          <button
            onClick={() => onSetRelevancia(relevancia === true ? null : true)}
            aria-label="Relevante"
            style={{ ...iconButtonStyle, background: relevancia === true ? "var(--orange-600)" : "transparent", color: relevancia === true ? "#fff" : "var(--text-secondary)" }}
          >
            <ThumbsUp size={16} />
          </button>
          <button
            onClick={() => onSetRelevancia(relevancia === false ? null : false)}
            aria-label="Não relevante"
            style={{ ...iconButtonStyle, background: relevancia === false ? "var(--orange-600)" : "transparent", color: relevancia === false ? "#fff" : "var(--text-secondary)" }}
          >
            <ThumbsDown size={16} />
          </button>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={onOpenFullDoc} style={secondaryButtonStyle}>
            Abrir documento completo
          </button>
          <button onClick={onToggleSave} style={isSaved ? secondaryButtonStyle : primaryButtonStyle}>
            {isSaved ? "Remover do dossiê" : "Salvar no dossiê"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <span style={{ color: "var(--text-tertiary)" }}>{label}</span>
      <span style={{ color: "var(--text-primary)", textAlign: "right" }}>{value}</span>
    </div>
  );
}

const iconButtonStyle: React.CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-default)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
  background: "var(--neutral-0)",
};

const primaryButtonStyle: React.CSSProperties = {
  padding: "8px 16px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: "var(--radius-sm)",
  border: "none",
  background: "var(--orange-600)",
  color: "#fff",
  cursor: "pointer",
};

const secondaryButtonStyle: React.CSSProperties = {
  padding: "8px 16px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-default)",
  background: "var(--neutral-0)",
  color: "var(--text-primary)",
  cursor: "pointer",
};
