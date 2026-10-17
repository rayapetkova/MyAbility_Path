-- Пусни целия файл в Supabase -> SQL Editor -> Run
create table reviews(
  id bigint generated always as identity primary key,
  osm_id text not null,                       -- напр. "node/123456" от OpenStreetMap
  rating int not null check (rating between 1 and 5),
  created_at timestamptz default now());
create table reports(
  id bigint generated always as identity primary key,
  osm_id text not null,
  type text not null check (type in ('Няма хартия','Заключено','Мръсно','Не работи')),
  created_at timestamptz default now());
create index on reviews(osm_id);
create index on reports(osm_id);

-- Обобщение: средна оценка, брой отзиви, активни проблеми за последните 24ч
create view toilet_stats as
select o.osm_id,
  coalesce(r.avg_rating,0) as avg_rating,
  coalesce(r.cnt,0) as review_count,
  coalesce(p.blocking,0) as blocking_reports
from (select osm_id from reviews union select osm_id from reports) o
left join (select osm_id, avg(rating)::numeric(3,2) avg_rating, count(*) cnt from reviews group by osm_id) r using(osm_id)
left join (select osm_id, count(*) filter (where type in ('Заключено','Не работи') and created_at > now() - interval '24 hours') blocking from reports group by osm_id) p using(osm_id);

-- Сигурност: всеки може да ДОБАВЯ, но чете само обобщението
alter table reviews enable row level security;
alter table reports enable row level security;
create policy "anon add review" on reviews for insert to anon with check (true);
create policy "anon add report" on reports for insert to anon with check (true);
grant select on toilet_stats to anon;
