-- Temel şema. Fiyat geçmişi yalnızca 4 saatlik ve günlük olarak saklanır;
-- haftalık / aylık / 3 aylık barlar günlük tablodan view ile üretilir.

CREATE TABLE symbols (
    id            serial PRIMARY KEY,
    market        text NOT NULL CHECK (market IN ('BIST', 'US')),
    exchange      text NOT NULL,              -- BIST, NASDAQ, NYSE ...
    ticker        text NOT NULL,              -- THYAO, AAPL ...
    name          text,
    sector        text,
    indexes       text[] NOT NULL DEFAULT '{}',  -- XU030, XU100, SPX, NDX
    active        boolean NOT NULL DEFAULT true,
    backfilled_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (exchange, ticker)
);
CREATE INDEX symbols_market_idx ON symbols (market);

-- Günlük barlar: "day" borsanın yerel saatine göre işlem günüdür.
CREATE TABLE bars_1d (
    symbol_id integer NOT NULL REFERENCES symbols (id) ON DELETE CASCADE,
    day       date NOT NULL,
    open      double precision NOT NULL,
    high      double precision NOT NULL,
    low       double precision NOT NULL,
    close     double precision NOT NULL,
    volume    double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol_id, day)
);

-- 4 saatlik barlar: "ts" barın açılış zamanıdır (UTC).
CREATE TABLE bars_4h (
    symbol_id integer NOT NULL REFERENCES symbols (id) ON DELETE CASCADE,
    ts        timestamptz NOT NULL,
    open      double precision NOT NULL,
    high      double precision NOT NULL,
    low       double precision NOT NULL,
    close     double precision NOT NULL,
    volume    double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol_id, ts)
);

CREATE VIEW bars_1w AS
SELECT symbol_id,
       date_trunc('week', day::timestamp)::date AS day,
       (array_agg(open ORDER BY day))[1]       AS open,
       max(high)                               AS high,
       min(low)                                AS low,
       (array_agg(close ORDER BY day DESC))[1] AS close,
       sum(volume)                             AS volume
FROM bars_1d
GROUP BY symbol_id, date_trunc('week', day::timestamp)::date;

CREATE VIEW bars_1mo AS
SELECT symbol_id,
       date_trunc('month', day::timestamp)::date AS day,
       (array_agg(open ORDER BY day))[1]         AS open,
       max(high)                                 AS high,
       min(low)                                  AS low,
       (array_agg(close ORDER BY day DESC))[1]   AS close,
       sum(volume)                               AS volume
FROM bars_1d
GROUP BY symbol_id, date_trunc('month', day::timestamp)::date;

CREATE VIEW bars_3mo AS
SELECT symbol_id,
       date_trunc('quarter', day::timestamp)::date AS day,
       (array_agg(open ORDER BY day))[1]           AS open,
       max(high)                                   AS high,
       min(low)                                    AS low,
       (array_agg(close ORDER BY day DESC))[1]     AS close,
       sum(volume)                                 AS volume
FROM bars_1d
GROUP BY symbol_id, date_trunc('quarter', day::timestamp)::date;

-- 15 dk gecikmeli anlık fiyatlar (geçmiş tutulmaz, sadece son değer).
CREATE TABLE live_quotes (
    symbol_id   integer PRIMARY KEY REFERENCES symbols (id) ON DELETE CASCADE,
    price       double precision NOT NULL,
    open        double precision,
    high        double precision,
    low         double precision,
    volume      double precision,
    change_pct  double precision,
    update_mode text,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

-- Her sembol ve periyot için son barın indikatör değerleri (tarayıcı bunu kullanır).
CREATE TABLE indicator_snapshots (
    symbol_id  integer NOT NULL REFERENCES symbols (id) ON DELETE CASCADE,
    timeframe  text NOT NULL,
    bar_time   timestamptz NOT NULL,
    vals       jsonb NOT NULL,
    prev       jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol_id, timeframe)
);

CREATE TABLE watchlists (
    id         serial PRIMARY KEY,
    name       text NOT NULL,
    position   integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE watchlist_items (
    watchlist_id integer NOT NULL REFERENCES watchlists (id) ON DELETE CASCADE,
    symbol_id    integer NOT NULL REFERENCES symbols (id) ON DELETE CASCADE,
    position     integer NOT NULL DEFAULT 0,
    added_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (watchlist_id, symbol_id)
);

-- kind = 'price'      : anlık fiyat bir seviyeyi kestiğinde (seans içinde, gecikmeli veriyle)
-- kind = 'expression' : tarayıcı ifadesi bar kapanışında doğru olduğunda
CREATE TABLE alerts (
    id                serial PRIMARY KEY,
    kind              text NOT NULL CHECK (kind IN ('price', 'expression')),
    symbol_id         integer REFERENCES symbols (id) ON DELETE CASCADE,
    watchlist_id      integer REFERENCES watchlists (id) ON DELETE CASCADE,
    timeframe         text NOT NULL DEFAULT '1d',
    operator          text CHECK (operator IN ('cross_up', 'cross_down')),
    value             double precision,
    expression        text,
    mode              text NOT NULL DEFAULT 'once' CHECK (mode IN ('once', 'repeat')),
    note              text,
    active            boolean NOT NULL DEFAULT true,
    state             jsonb NOT NULL DEFAULT '{}',
    last_triggered_at timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (kind <> 'price' OR (symbol_id IS NOT NULL AND operator IS NOT NULL AND value IS NOT NULL)),
    CHECK (kind <> 'expression' OR (expression IS NOT NULL AND (symbol_id IS NOT NULL OR watchlist_id IS NOT NULL)))
);

CREATE TABLE alert_events (
    id           bigserial PRIMARY KEY,
    alert_id     integer REFERENCES alerts (id) ON DELETE SET NULL,
    scan_id      integer,
    symbol_id    integer REFERENCES symbols (id) ON DELETE CASCADE,
    message      text NOT NULL,
    triggered_at timestamptz NOT NULL DEFAULT now(),
    seen         boolean NOT NULL DEFAULT false
);
CREATE INDEX alert_events_time_idx ON alert_events (triggered_at DESC);

-- Kayıtlı (periyodik) taramalar.
-- schedule: 'after_close' (ilgili borsanın gün sonu güncellemesinden sonra),
--           bir cron ifadesi ('0 10 * * 1-5', Europe/Istanbul saatiyle) veya 'manual'.
CREATE TABLE scans (
    id           serial PRIMARY KEY,
    name         text NOT NULL,
    expression   text NOT NULL,
    timeframe    text NOT NULL DEFAULT '1d',
    markets      text[] NOT NULL DEFAULT '{BIST,US}',
    indexes      text[] NOT NULL DEFAULT '{}',
    watchlist_id integer REFERENCES watchlists (id) ON DELETE SET NULL,
    sort_by      text,
    schedule     text NOT NULL DEFAULT 'after_close',
    notify       boolean NOT NULL DEFAULT true,
    active       boolean NOT NULL DEFAULT true,
    last_run_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE scan_results (
    id          bigserial PRIMARY KEY,
    scan_id     integer NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
    run_at      timestamptz NOT NULL DEFAULT now(),
    match_count integer NOT NULL,
    matches     jsonb NOT NULL,
    new_matches jsonb NOT NULL
);
CREATE INDEX scan_results_scan_idx ON scan_results (scan_id, run_at DESC);

-- Grafik üzerindeki yatay çizgiler vb.
CREATE TABLE drawings (
    id         serial PRIMARY KEY,
    symbol_id  integer NOT NULL REFERENCES symbols (id) ON DELETE CASCADE,
    kind       text NOT NULL,
    data       jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_runs (
    id          bigserial PRIMARY KEY,
    job         text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL DEFAULT 'running',
    message     text
);
CREATE INDEX job_runs_job_idx ON job_runs (job, started_at DESC);
