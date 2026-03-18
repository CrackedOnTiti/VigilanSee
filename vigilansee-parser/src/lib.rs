use s3::bucket::Bucket;
use s3::creds::Credentials;
use s3::error::S3Error;
use s3::region::Region;

pub async fn bucket_pull() -> Result<(), S3Error> {
    dotenvy::dotenv().ok();
    let bucket_name = "VigilanSee-Dem";
    let region = Region::Custom {
    region: "eu-central-003".to_string(),
    endpoint: "https://s3.eu-central-003.backblazeb2.com".to_string(),
    };
    let credentials = Credentials::default().unwrap();
    
    let bucket = Bucket::new(bucket_name, region, credentials)?;
    
    let list = bucket.list("".to_string(), None).await?;
    
    for dem in list {
        println!("{:?}", dem)
    }
    Ok(())
}

    #[cfg(test)]
    mod tests {
        use super::*;
    
        #[tokio::test]
        async fn test_bucket_pull() {
            bucket_pull().await.unwrap();
        }
    }
