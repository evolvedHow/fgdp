import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type { ScoredPlan } from './types.js';

interface FdEnsembleSchema extends DBSchema {
  scoredPlans: {
    key: string;
    value: ScoredPlan;
    indexes: { 'by-run': string };
  };
}

const DB_NAME = 'fdensemble';
const DB_VERSION = 1;

let _db: IDBPDatabase<FdEnsembleSchema> | null = null;

async function getDB(): Promise<IDBPDatabase<FdEnsembleSchema>> {
  if (!_db) {
    _db = await openDB<FdEnsembleSchema>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        const store = db.createObjectStore('scoredPlans', { keyPath: 'id' });
        store.createIndex('by-run', 'run_id');
      },
    });
  }
  return _db;
}

export async function saveScoredPlan(plan: ScoredPlan): Promise<void> {
  const db = await getDB();
  await db.put('scoredPlans', plan);
}

export async function getAllScoredPlans(): Promise<ScoredPlan[]> {
  const db = await getDB();
  return db.getAll('scoredPlans');
}

export async function deleteScoredPlan(id: string): Promise<void> {
  const db = await getDB();
  await db.delete('scoredPlans', id);
}

export async function getScoredPlansByRun(runId: string): Promise<ScoredPlan[]> {
  const db = await getDB();
  return db.getAllFromIndex('scoredPlans', 'by-run', runId);
}
