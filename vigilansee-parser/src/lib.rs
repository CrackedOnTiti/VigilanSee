use s3::bucket::Bucket;
use s3::creds::Credentials;
use s3::error::S3Error;
use s3::region::Region;


/// Represents a CS2 demo file stored in R2 cloud storage
pub struct DemFile {
    pub last_modified: String,
    pub e_tag: String,
    pub name: String,
    pub size: u64
}


struct R2Client {
    bucket: Box<Bucket>
}


impl R2Client {
    pub fn new() -> Result<Self, S3Error> {
        dotenvy::dotenv().ok();
        let bucket_name = "VigilanSee-Dem";
        let region = Region::Custom {
        region: "auto".to_string(),
        endpoint: "https://dc7194b4e18cb86f95ae13e7f5725c5d.r2.cloudflarestorage.com".to_string(),
        };
        let credentials = Credentials::default().unwrap();
        Ok(R2Client { bucket: Bucket::new(bucket_name, region, credentials)?})
    }


    /// Fetches R2 and returns a Vec<DemFile> with all the currunt available files, 
    /// in case of error returns S3Error
    pub async fn list_bucket(&self) -> Result<Vec<DemFile>, S3Error> {
        let bucket = &self.bucket;
        let list = bucket.list("".to_string(), None).await?;
        let mut dem_files: Vec<DemFile> = Vec::new();

        if list.is_empty() {
            println!("Bucket: {} is empty", bucket.name);
            return Ok(dem_files);
        }

        for bucket_result in list {
            for obj in bucket_result.contents {
                if obj.key.ends_with(".dem") {
                    dem_files.push(DemFile {
                        last_modified: obj.last_modified,
                        e_tag: obj.e_tag.unwrap_or_default(),
                        name: obj.key,
                        size: obj.size
                    });
                }
            }
        }

        let mut val = 1;
        for dem in &dem_files {
            println!("Dem file n{}:\n", val); 
            println!("name {}\nsize {}\nlast modified {}\ne tag {}\n", dem.name, dem.size, dem.last_modified, dem.e_tag);
            val += 1; 
        }
        Ok(dem_files)
    }


    /// Downloads all present .dem files from R2 and returns void, 
    /// in case of error returns S3Error
    pub async fn download_all_dem(&self, target: Vec<DemFile>) -> Result<(), S3Error> {
        for dem in target {
            self.download_dem(dem).await?;
        }
        Ok(())
    }


    /// Downloads a file from R2 and returns void,
    /// in case of error returns S3Error
    pub async fn download_dem(&self, target: DemFile) -> Result<(), S3Error> {
        let bucket = &self.bucket;

        let target_data = bucket.get_object(&target.name).await?;
        let target_bytes = &target_data.bytes();
        tokio::fs::create_dir_all("dem").await.unwrap();
        tokio::fs::write(format!("dem/{}", &target.name), &target_bytes).await.unwrap();

        Ok(())
    }
}


/// TODO reception of vector and after CLI or whatever we select and pull necesary


#[cfg(test)]
mod tests {
    use super::*;
    
    #[tokio::test]
    async fn test_impl_r2_client() {
        R2Client::new().unwrap();
    }
    #[tokio::test]
    async fn test_list_bucket() {
        R2Client::new().unwrap().list_bucket().await.unwrap();
    }
    // #[tokio::test]
    // async fn test_download_all_dem() {
    //     download_all_dem(list_bucket().await.unwrap()).await.unwrap();
    // }
    // #[tokio::test]
    // async fn test_download_dem() {
    //     download_dem(list_bucket().await.unwrap().into_iter().next().unwrap()).await.unwrap();
    // }
}
