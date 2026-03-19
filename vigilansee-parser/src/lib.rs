use s3::bucket::Bucket;
use s3::creds::Credentials;
use s3::error::S3Error;
use s3::region::Region;

pub async fn list_bucket() -> Result<(), S3Error> {
    dotenvy::dotenv().ok();
    let bucket_name = "VigilanSee-Dem";
    let region = Region::Custom {
    region: "eu-central-003".to_string(),
    endpoint: "https://s3.eu-central-003.backblazeb2.com".to_string(),
    };
    let credentials = Credentials::default().unwrap();
    let bucket = Bucket::new(bucket_name, region, credentials)?;
    let list = bucket.list("".to_string(), None).await?;

    if list.is_empty() {
        println!("Bucket: {} is empty", bucket_name);
        return Ok(());
    }
    
    for dem in list {
        println!("{:?}", dem);
    }
    Ok(())
}

    #[cfg(test)]
    mod tests {
        use super::*;
    
        #[tokio::test]
        async fn test_list_bucket() {
            list_bucket().await.unwrap();
        }
    }
