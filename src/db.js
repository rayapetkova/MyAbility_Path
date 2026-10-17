// Отзиви и доклади се пазят в Supabase (Postgres)
import { createClient } from '@supabase/supabase-js';
const sb = createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_ANON_KEY);

export async function getStats(ids) {
  if (!ids.length) return {};
  const { data, error } = await sb.from('toilet_stats').select('*').in('osm_id', ids);
  if (error) { console.error(error); return {}; }
  return Object.fromEntries(data.map(d => [d.osm_id, d]));
}
export const addReview = (osm_id, rating) => sb.from('reviews').insert({ osm_id, rating });
export const addReport = (osm_id, type) => sb.from('reports').insert({ osm_id, type });
