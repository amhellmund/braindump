---
name: react-dev
description: >
    Activate this skill for any task involving writing React/TypeScript source code
    in the frontend/ directory.

    This includes:
      - adding new components
      - fixing bugs
      - adding types
      - updating styles
      - writing or updating tests
      - reviewing frontend code
---

# React Development Skill

## Core Principles

1. **TypeScript only** — no `.js` or `.jsx` files; every file is `.ts` or `.tsx`.
2. **Strict mode** — `tsconfig.json` enables `"strict": true`; never use `any` unless absolutely unavoidable and always add a comment explaining why.
3. **Functional components only** — no class components; use hooks for all state and side-effects.
4. **Co-locate styles** — every component has a matching `.css` file; no inline `style={{}}` except for dynamic values that cannot be expressed in CSS.
5. **Fail visibly** — surface errors through `useErrorToast()` so users always see what went wrong.

---

## General Coding Guidelines

Before finalising any frontend output, verify:

- [ ] **File extension** — `.ts` for pure logic, `.tsx` for JSX-containing files
- [ ] **No JS files** — `eslint.config.js` is the only `.js` file and is tooling config, not app code
- [ ] **Named exports** — prefer named exports for components; default export only for the component itself (required by react-refresh)
- [ ] **Typed props** — every component has an explicit `interface Props { … }` or inline type
- [ ] **No `any`** — use `unknown` + narrowing, generics, or precise union types instead
- [ ] **Hook rules** — hooks called unconditionally at the top of the component; never inside loops, conditions, or nested functions
- [ ] **Exhaustive deps** — `useEffect` / `useCallback` / `useMemo` dependency arrays are complete; add a comment if a dep is intentionally omitted
- [ ] **Event handlers** — typed with `React.MouseEvent`, `React.ChangeEvent<HTMLInputElement>`, etc.
- [ ] **Keys** — list renders use stable, unique keys (IDs, not array indices)
- [ ] **Accessibility** — interactive elements have `aria-label` or visible label; icon-only buttons have `title` and `aria-label`
- [ ] **CSS class naming** — kebab-case; scoped with a component prefix (e.g. `.query-bar`, `.query-input`)

---

## Project-Specific Guidelines

- [ ] **API calls** — always go through `api.ts`; never call `fetch` directly in a component
- [ ] **Error handling** — wrap async calls in `try/catch` and call `pushError()` from `useErrorToast()`
- [ ] **Types** — shared domain types live in `types.ts`; API-response shapes live in `api.ts` alongside the call that returns them
- [ ] **State lifting** — local state stays local; lift only when two or more siblings need it
- [ ] **No prop drilling past two levels** — use React context (following the `ErrorToast` provider pattern) for cross-cutting concerns

---

## Patterns & Best Practices

### Component structure

```tsx
// components/MyWidget.tsx
import { useState, useCallback } from 'react'
import { useErrorToast } from './ErrorToast'
import './MyWidget.css'

interface Props {
  label: string
  onConfirm: (value: string) => void
}

export default function MyWidget({ label, onConfirm }: Props) {
  const { pushError } = useErrorToast()
  const [value, setValue] = useState('')

  const handleSubmit = useCallback(async () => {
    try {
      await someApiCall(value)
      onConfirm(value)
    } catch (err: unknown) {
      pushError('Failed to submit', String(err))
    }
  }, [value, onConfirm])

  return (
    <div className="my-widget">
      <label className="my-widget-label">{label}</label>
      <input
        className="my-widget-input"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && handleSubmit()}
      />
      <button className="my-widget-btn" onClick={handleSubmit}>
        Confirm
      </button>
    </div>
  )
}
```

### Typing async state

```tsx
// Explicit loading / error / data pattern
const [data, setData] = useState<Spike[] | null>(null)
const [loading, setLoading] = useState(false)

useEffect(() => {
  let cancelled = false
  setLoading(true)
  fetchSpikes()
    .then(spikes => { if (!cancelled) setData(spikes) })
    .catch(err => pushError('Load failed', String(err)))
    .finally(() => { if (!cancelled) setLoading(false) })
  return () => { cancelled = true }
}, [])
```

### Context provider pattern

```tsx
// Follow the ErrorToast pattern for cross-cutting concerns:
// 1. Define the context value interface
// 2. Create the context with a safe no-op default
// 3. Export a custom hook `useFoo()`
// 4. Export a `FooProvider` that wraps children

interface FooContextValue { doSomething: () => void }
const FooContext = createContext<FooContextValue>({ doSomething: () => {} })
export function useFoo() { return useContext(FooContext) }
export function FooProvider({ children }: { children: React.ReactNode }) { … }
```

### Adding an API call

```ts
// api.ts — add alongside the function that uses the new shape
export interface MyNewResponse {
  id: string
  value: number
}

export async function fetchMyThing(id: string): Promise<MyNewResponse> {
  return request<MyNewResponse>(`/my-thing/${id}`)
}
```

---

## Tooling

| Tool | Purpose | Run |
|------|---------|-----|
| **Vite** | Dev server (port 5173) + production build | `npm run dev` / `npm run build` |
| **TypeScript** | Type checking | `npx tsc --noEmit` |
| **ESLint** | Linting (typescript-eslint + react-hooks + react-refresh) | `npm run lint` |

The Vite dev server proxies `/api` → `http://localhost:8000` and `/api` websockets, so the backend must be running on port 8000 during development.

Production assets are compiled into `frontend/dist/` and bundled into the wheel by `tools/hatch_build.py`.

---

## Debugging Tips

```bash
# Type-check without building
npx tsc --noEmit

# Lint the source
npm run lint

# Inspect the production bundle contents
npx vite-bundle-visualizer   # or: unzip -l ../dist/*.whl | grep frontend
```
