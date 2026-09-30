'use client'

import { createContext, useContext, type ReactNode } from 'react'

import { getHelloAdaSite, setHelloAdaSite, type HelloAdaSiteConfig } from './site'

const HelloAdaSiteContext = createContext<HelloAdaSiteConfig>(getHelloAdaSite())

export function HelloAdaSiteProvider({ config, children }: { config: HelloAdaSiteConfig; children: ReactNode }) {
  setHelloAdaSite(config)
  return <HelloAdaSiteContext.Provider value={config}>{children}</HelloAdaSiteContext.Provider>
}

export const useHelloAdaSite = () => useContext(HelloAdaSiteContext)
