import {DatabaseSync} from 'node:sqlite';
export const sqlite=new DatabaseSync(':memory:');
sqlite.exec('CREATE TABLE demo_sessions(id TEXT PRIMARY KEY,payload TEXT NOT NULL,busy INTEGER DEFAULT 0); CREATE TABLE demo_budget(id TEXT PRIMARY KEY,spent REAL DEFAULT 0,reserved REAL DEFAULT 0)');
export const env={
  OPENAI_API_KEY:'mock-key-never-transmitted',
  DEMO_BUDGET_USD:'3',
  DB:{prepare(sql:string){
    let args:any[]=[];
    return {
      bind(...values:any[]){args=values;return this},
      async first(){return sqlite.prepare(sql).get(...args)||null},
      async run(){const result=sqlite.prepare(sql).run(...args);return {meta:{changes:Number(result.changes)}}}
    };
  }}
};
