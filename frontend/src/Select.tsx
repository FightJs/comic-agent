import { createPortal } from "react-dom";
import {
  Children,
  isValidElement,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type ButtonHTMLAttributes,
} from "react";
import { Check, ChevronDown } from "lucide-react";
import "./select.css";
type Props = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "value" | "onChange" | "children"
> & {
  value: string | number | undefined;
  children: ReactNode;
  onChange: (event: { target: { value: string } }) => void;
};
function text(node: ReactNode): string {
  return Children.toArray(node)
    .map((n) =>
      isValidElement<{ children?: ReactNode }>(n)
        ? text(n.props.children)
        : String(n),
    )
    .join("");
}
export function Select({
  value,
  children,
  onChange,
  disabled,
  className = "",
  ...props
}: Props) {
  const options = Children.toArray(children)
    .filter(
      isValidElement<{
        value?: string | number;
        children?: ReactNode;
        disabled?: boolean;
      }>,
    )
    .map((n) => ({
      value: String(n.props.value ?? text(n.props.children)),
      label: text(n.props.children),
      disabled: !!n.props.disabled,
    }));
  const selected = options.findIndex((o) => o.value === String(value));
  const [open, setOpen] = useState(false),
    [active, setActive] = useState(0);
  const [position, setPosition] = useState({
    left: 0,
    top: 0,
    width: 0,
    maxHeight: 280,
  });
  const trigger = useRef<HTMLButtonElement>(null),
    list = useRef<HTMLDivElement>(null);
  const id = useId(),
    search = useRef({ text: "", time: 0 });
  const close = () => setOpen(false);
  const choose = (index: number) => {
    const option = options[index];
    if (!option || option.disabled) return;
    onChange({ target: { value: option.value } });
    close();
    trigger.current?.focus();
  };
  const show = () => {
    if (disabled || !options.some((o) => !o.disabled)) return;
    setActive(
      selected >= 0 && !options[selected].disabled
        ? selected
        : options.findIndex((o) => !o.disabled),
    );
    setOpen(true);
  };
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = trigger.current!.getBoundingClientRect(),
        margin = 8;
      const below = window.innerHeight - r.bottom - margin,
        above = r.top - margin;
      const width = Math.min(Math.max(r.width, 180), window.innerWidth - 16);
      const menu = list.current!;
      menu.style.width = `${width}px`;
      const naturalHeight = menu.scrollHeight + 2;
      const up = below < Math.min(280, naturalHeight) && above > below;
      const maxHeight = Math.max(40, Math.min(280, (up ? above : below) - 4));
      setPosition({
        left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
        top: up
          ? Math.max(8, r.top - Math.min(maxHeight, naturalHeight) - 4)
          : r.bottom + 4,
        width,
        maxHeight,
      });
    };
    list.current?.showPopover?.();
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      list.current?.hidePopover?.();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, options.length]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (e: PointerEvent) => {
      if (
        !trigger.current?.contains(e.target as Node) &&
        !list.current?.contains(e.target as Node)
      )
        close();
    };
    const focus = (e: FocusEvent) => {
      if (
        !trigger.current?.contains(e.target as Node) &&
        !list.current?.contains(e.target as Node)
      )
        close();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", focus);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", focus);
    };
  }, [open]);
  useEffect(() => {
    if (open)
      document
        .getElementById(`${id}-${active}`)
        ?.scrollIntoView?.({ block: "nearest" });
  }, [active, open, id]);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  return (
    <>
      <button
        {...props}
        type="button"
        ref={trigger}
        disabled={disabled || !options.length}
        className={`theme-select ${className}`}
        title={options[selected]?.label}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        onClick={() => (open ? close() : show())}
        onKeyDown={(e) => {
          if (
            ["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(
              e.key,
            )
          ) {
            e.preventDefault();
            if (!open) {
              show();
              return;
            }
            if (e.key === "Enter" || e.key === " ") {
              choose(active);
              return;
            }
            const enabled = options
              .map((o, i) => (o.disabled ? -1 : i))
              .filter((i) => i >= 0);
            const index = enabled.indexOf(active);
            setActive(
              e.key === "Home"
                ? enabled[0]
                : e.key === "End"
                  ? enabled[enabled.length - 1]
                  : enabled[
                      (index +
                        (e.key === "ArrowDown" ? 1 : -1) +
                        enabled.length) %
                        enabled.length
                    ],
            );
          } else if (e.key === "Escape" && open) {
            e.preventDefault();
            e.stopPropagation();
            close();
          } else if (e.key === "Tab") close();
          else if (
            e.key.length === 1 &&
            !e.ctrlKey &&
            !e.metaKey &&
            !e.altKey
          ) {
            const now = Date.now();
            search.current = {
              text:
                (now - search.current.time > 700 ? "" : search.current.text) +
                e.key.toLocaleLowerCase(),
              time: now,
            };
            const found = options.findIndex(
              (o) =>
                !o.disabled &&
                o.label.toLocaleLowerCase().startsWith(search.current.text),
            );
            if (found >= 0) {
              if (!open) show();
              setActive(found);
            }
          }
        }}
      >
        <span className="theme-select-value">
          {options[selected]?.label ||
            (options.length ? "请选择" : "暂无可选项")}
        </span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <div
            ref={list}
            id={id}
            popover="manual"
            role="listbox"
            aria-label={props["aria-label"] || "可选项"}
            className="theme-select-menu"
            style={position}
            onMouseDown={(e) => e.preventDefault()}
          >
            {options.map((o, i) => (
              <div
                key={o.value}
                id={`${id}-${i}`}
                role="option"
                aria-selected={i === selected}
                aria-disabled={o.disabled || undefined}
                className={`theme-select-option ${i === active ? "is-active" : ""}`}
                onPointerMove={() => !o.disabled && setActive(i)}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  choose(i);
                }}
              >
                <span>{o.label}</span>
                {i === selected && <Check size={15} aria-hidden="true" />}
              </div>
            ))}
          </div>,
          trigger.current?.closest("dialog") || document.body,
        )}
    </>
  );
}
