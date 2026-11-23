import { createContext, useCallback, useContext, useState, type MouseEvent, type ReactNode } from 'react';

type Show = (e: MouseEvent, content: ReactNode) => void;
const Ctx = createContext<{ show: Show; hide: () => void }>({ show: () => undefined, hide: () => undefined });

/** One floating tooltip for the whole app. Follows the mouse. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null);

  const show = useCallback<Show>((e, content) => setTip({ x: e.clientX, y: e.clientY, content }), []);
  const hide = useCallback(() => setTip(null), []);

  const left = tip ? Math.min(tip.x + 14, window.innerWidth - 300) : 0;
  const top = tip ? (tip.y + 160 > window.innerHeight ? tip.y - 14 : tip.y + 14) : 0;

  return (
    <Ctx.Provider value={{ show, hide }}>
      {children}
      {tip && (
        <div className="tooltip" style={{ left, top, transform: tip.y + 160 > window.innerHeight ? 'translateY(-100%)' : undefined }}>
          {tip.content}
        </div>
      )}
    </Ctx.Provider>
  );
}

/** Spread onto any element: <div {...useHover(<b>hi</b>)} /> */
export function useHover() {
  const { show, hide } = useContext(Ctx);
  return (content: ReactNode) => ({
    onMouseEnter: (e: MouseEvent) => show(e, content),
    onMouseMove: (e: MouseEvent) => show(e, content),
    onMouseLeave: hide,
  });
}
