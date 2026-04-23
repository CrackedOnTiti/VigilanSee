use sqlx::{PgPool, postgres::PgPoolOptions};

pub async fn connect(database_url: &str) -> PgPool {
    PgPoolOptions::new()
        .max_connections(5)
        .connect(database_url)
        .await
        .expect("Failed to connect to PostgreSQL")
}

pub async fn init_db(pool: &PgPool) {
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS players (
            id          SERIAL PRIMARY KEY,
            steam_id    VARCHAR(20) NOT NULL UNIQUE,
            risk_factor FLOAT NOT NULL DEFAULT 0.0
        )"
    )
    .execute(pool)
    .await
    .expect("Failed to run DB migrations");

    println!("DB initialized.");
}
