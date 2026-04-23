use vigilansee_db::{connect, init_db};

#[tokio::main]
async fn main() {
    let database_url = std::env::var("DATABASE_URL")
        .expect("DATABASE_URL must be set");

    let pool = connect(&database_url).await;
    init_db(&pool).await;

    vigilansee_api::web::serve().await;
}
