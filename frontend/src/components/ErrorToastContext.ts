import { createContext, useContext } from 'react'

export interface ErrorContextValue {
  pushError: (title: string, detail: string) => void
}

export const ErrorContext = createContext<ErrorContextValue>({ pushError: () => {} })

export function useErrorToast() {
  return useContext(ErrorContext)
}
