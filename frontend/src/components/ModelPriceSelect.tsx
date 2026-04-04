import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ModelPriceRow } from "@/services/billingApi";

type Props = {
  value: string;
  onChange: (modelId: string) => void;
  models: ModelPriceRow[];
  disabled?: boolean;
};

function pickPrices(m: ModelPriceRow) {
  const p = m.prompt_price_cny_per_million_tokens || m.price_cny_per_million_tokens || 0;
  const c = m.completion_price_cny_per_million_tokens || m.price_cny_per_million_tokens || 0;
  return { p, c };
}

function PriceBadges({ p, c }: { p: number; c: number }) {
  return (
    <div className="flex shrink-0 flex-col items-end gap-0.5 text-right">
      <div className="flex items-center gap-1 group/price cursor-help" title="大模型的 Prompt (输入) 与 Completion (输出) 价格，单位为人民币/百万 Token">
        <span className="text-[10px] tabular-nums text-foreground/80 dark:text-muted-foreground">
          入 <span className="font-semibold text-foreground dark:font-medium dark:text-foreground/90 group-hover/price:text-primary transition-colors">¥{p.toFixed(2)}</span>
          <span className="text-foreground/70 dark:text-muted-foreground/80"> /M</span>
        </span>
        <HelpCircle className="h-2.5 w-2.5 text-foreground/50 dark:text-muted-foreground/50 group-hover/price:text-primary/70 transition-colors" />
      </div>
      <span className="text-[10px] tabular-nums text-foreground/80 dark:text-muted-foreground">
        出 <span className="font-semibold text-foreground dark:font-medium dark:text-foreground/90 group-hover/price:text-primary transition-colors">¥{c.toFixed(2)}</span>
        <span className="text-foreground/70 dark:text-muted-foreground/80"> /M</span>
      </span>
    </div>
  );
}

function resolvePortalContainer(triggerEl: HTMLElement | null): HTMLElement {
  if (!triggerEl) return document.body;
  // Radix Dialog wraps content in RemoveScroll with shards=[dialog content only].
  // Portals to document.body sit outside that shard and cannot scroll (wheel / scrollbar).
  const dialog = triggerEl.closest('[role="dialog"]') as HTMLElement | null;
  return dialog ?? document.body;
}

/** When the dropdown is portaled inside a transformed Dialog, `position:fixed` is relative to that dialog, not the viewport — use dialog-local offsets. */
function computePanelGeometry(triggerEl: HTMLElement) {
  const rect = triggerEl.getBoundingClientRect();
  const portal = resolvePortalContainer(triggerEl);
  const dialog = triggerEl.closest('[role="dialog"]') as HTMLElement | null;

  if (dialog && portal === dialog) {
    const d = dialog.getBoundingClientRect();
    const maxH = Math.max(
      160,
      Math.min(Math.floor(window.innerHeight * 0.5), d.bottom - rect.bottom - 12)
    );
    const maxW = Math.min(d.width - 16, window.innerWidth - 16);
    const width = Math.min(Math.max(rect.width, 280), maxW);
    let left = rect.left - d.left;
    if (left + width > d.width - 8) {
      left = Math.max(8, d.width - width - 8);
    }
    return {
      top: rect.bottom - d.top + 6,
      left,
      width,
      maxH,
    };
  }

  const maxH = Math.max(
    160,
    Math.min(Math.floor(window.innerHeight * 0.5), window.innerHeight - rect.bottom - 12)
  );
  const width = Math.min(Math.max(rect.width, 280), window.innerWidth - 16);
  let left = rect.left;
  if (left + width > window.innerWidth - 8) {
    left = Math.max(8, window.innerWidth - width - 8);
  }
  return {
    top: rect.bottom + 6,
    left,
    width,
    maxH,
  };
}

export function ModelPriceSelect({ value, onChange, models, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);
  const [panelBox, setPanelBox] = useState({ top: 0, left: 0, width: 0, maxH: 320 });

  const selected = models.find((m) => m.model_id === value);

  const updatePosition = () => {
    const el = triggerRef.current;
    if (!el) return;
    setPanelBox(computePanelGeometry(el));
  };

  useLayoutEffect(() => {
    if (!open) {
      setPortalContainer(null);
      return;
    }
    setPortalContainer(resolvePortalContainer(triggerRef.current));
    updatePosition();
    const onWin = () => updatePosition();
    window.addEventListener("resize", onWin);
    window.addEventListener("scroll", onWin, true);
    return () => {
      window.removeEventListener("resize", onWin);
      window.removeEventListener("scroll", onWin, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const triggerInner = selected ? (
    <div className="flex min-w-0 flex-1 items-start gap-3 text-left">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">
          {selected.display_name || selected.model_id}
        </p>
        <p className="truncate font-mono text-[11px] text-muted-foreground">{selected.model_id}</p>
      </div>
      <PriceBadges {...pickPrices(selected)} />
    </div>
  ) : (
    <div className="flex min-w-0 flex-1 text-left">
      <p className="text-sm text-muted-foreground">请选择模型（需在管理后台配置模型计价）</p>
    </div>
  );

  if (disabled || models.length === 0) {
    return (
      <div
        className={cn(
          "flex w-full items-center gap-2 rounded-xl border border-border/50 bg-muted/20 px-3 py-2.5",
          "text-muted-foreground"
        )}
      >
        {models.length === 0 ? (
          <p className="text-sm">暂无已启用模型，请管理员在「管理后台 → 模型计价」中添加。</p>
        ) : (
          triggerInner
        )}
      </div>
    );
  }

  const dropdown =
    open &&
    portalContainer &&
    createPortal(
      <div
        ref={panelRef}
        role="listbox"
        style={{
          position: "fixed",
          top: panelBox.top,
          left: panelBox.left,
          width: panelBox.width,
          zIndex: 200,
          maxHeight: panelBox.maxH,
          WebkitOverflowScrolling: "touch",
        }}
        className={cn(
          "overflow-y-auto overflow-x-hidden overscroll-contain touch-pan-y",
          "rounded-xl border border-border/60 bg-card/95 shadow-[0_16px_40px_-12px_rgba(0,0,0,0.35)] backdrop-blur-md",
          "animate-in fade-in-0 zoom-in-95 duration-150",
          "[scrollbar-width:thin] [scrollbar-color:hsl(var(--muted-foreground)/0.35)_transparent]"
        )}
      >
        <div className="space-y-0.5 p-1">
          {models.map((m) => {
            const { p, c } = pickPrices(m);
            const isOn = value === m.model_id;
            return (
              <button
                key={m.id}
                type="button"
                role="option"
                aria-selected={isOn}
                onClick={() => {
                  onChange(m.model_id);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
                  "hover:bg-primary/8",
                  isOn && "bg-primary/10 ring-1 ring-primary/15"
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium leading-tight">
                    {m.display_name || m.model_id}
                  </p>
                  <p className="truncate font-mono text-[10px] text-muted-foreground">{m.model_id}</p>
                </div>
                <PriceBadges p={p} c={c} />
                {isOn ? (
                  <Check className="mt-1 h-4 w-4 shrink-0 text-primary" />
                ) : (
                  <span className="w-4 shrink-0" />
                )}
              </button>
            );
          })}
        </div>
      </div>,
      portalContainer
    );

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => {
          setOpen((o) => {
            const next = !o;
            if (next && triggerRef.current) {
              setPanelBox(computePanelGeometry(triggerRef.current));
            }
            return next;
          });
        }}
        className={cn(
          "flex w-full items-stretch gap-2 rounded-xl border border-border/60 bg-background/50 px-3 py-2.5 text-left shadow-sm",
          "backdrop-blur-sm transition-[border-color,box-shadow] hover:border-primary/25 hover:bg-background/70",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
          open && "border-primary/35 ring-1 ring-primary/15"
        )}
      >
        {triggerInner}
        <ChevronDown
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180"
          )}
        />
      </button>
      {dropdown}
    </>
  );
}
