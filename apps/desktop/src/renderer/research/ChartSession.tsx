import React, { createContext, useContext } from "react";
import type { ChartPreferences } from "./ChartToolkit";

export interface FormulaDraft {
 name:string;script:string;parameters:{name:string;value:number}[];output?:string;
}
export interface ChartSession {
 preferences?:ChartPreferences;
 dailyPeriod?:"day"|"week"|"month"|"trading_days";
 tradingDays?:number;
 onChange?:()=>void;
 formula?:{draft:FormulaDraft;basis:"raw"|"adjusted";placement:"main"|"sub";applied?:{formula:FormulaDraft;basis:"raw"|"adjusted";placement:"main"|"sub"}};
}
const Context=createContext<ChartSession|null>(null);
export const useChartSession=()=>useContext(Context);
export function ChartSessionScope({session,children}:{session:ChartSession;children:React.ReactNode}) {return <Context.Provider value={session}>{children}</Context.Provider>;}
