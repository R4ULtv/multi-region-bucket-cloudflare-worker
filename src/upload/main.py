import math
import os
import requests
from requests.adapters import HTTPAdapter, Retry
import concurrent.futures
import argparse
from datetime import datetime


def upload_file(worker_endpoint, filename, partsize, headers):
    url = f"{worker_endpoint}{filename}"
    start_time = datetime.now()

    # Create the multipart upload
    uploadId = requests.post(url, params={"action": "mpu-create"}, headers=headers).json()["uploadId"]

    part_count = math.ceil(os.stat(filename).st_size / partsize)
    # Create an executor for up to 25 concurrent uploads.
    executor = concurrent.futures.ThreadPoolExecutor(25)
    # Submit a task to the executor to upload each part
    futures = [
        executor.submit(upload_part, filename, partsize, url, uploadId, index, headers)
        for index in range(part_count)
    ]
    concurrent.futures.wait(futures)
    # get the parts from the futures
    uploaded_parts = [future.result() for future in futures]

    # complete the multipart upload
    response = requests.post(
        url,
        params={"action": "mpu-complete", "uploadId": uploadId},
        json={"parts": uploaded_parts},
        headers=headers
    )
    if response.status_code == 200:
        print(f"{filename} has been successfully uploaded in {(datetime.now() - start_time).seconds} seconds. Bucket: {headers['X-Bucket-Name']}.")
    else:
        print(response.text)


def upload_part(filename, partsize, url, uploadId, index, headers):
    # Open the file in rb mode, which treats it as raw bytes rather than attempting to parse utf-8
    with open(filename, "rb") as file:
        file.seek(partsize * index)
        part = file.read(partsize)

    # Retry policy for when uploading a part fails
    s = requests.Session()
    retries = Retry(total=3, status_forcelist=[400, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))

    return s.put(
        url,
        params={
            "action": "mpu-uploadpart",
            "uploadId": uploadId,
            "partNumber": str(index + 1),
        },
        data=part,
        headers=headers
    ).json()

def main():
    parser = argparse.ArgumentParser(description='Upload a file to a Cloudflare Worker using multipart upload.')
    parser.add_argument("-f", "--file", type=str, required=True, help="The file to upload.")
    parser.add_argument("-e", "--endpoint", type=str, required=True, help="The endpoint to upload to.")
    parser.add_argument("-b", "--bucket", type=str, required=True, help="The bucket name to upload to. Can be a single bucket or a comma-separated list of buckets.")
    parser.add_argument("-p", "--partsize", type=int, required=False, default=10, help="The size of each part in megabytes.")
    parser.add_argument("-a", "--auth", type=str, required=False, help="The token to use for authentication.")

    args = parser.parse_args()

    if not os.path.exists(args.file):
        return print("File does not exist.")

    filename = args.file
    endpoint = args.endpoint

    # Check that the part size is between 5 and 100 megabytes. CloudFlare limitation.
    if args.partsize < 5 or args.partsize > 100:
        return print("Part size must be between 5 and 100 megabytes.")
    
    partsize = args.partsize * 1024 * 1024
    headers = {}
    buckets = []

    if args.auth is not None:
        headers["Authorization"] = "Bearer " + args.auth

    if "," in args.bucket:
        buckets = args.bucket.split(",")
    else:
        buckets = [args.bucket]

    # Upload the file to each bucket
    for bucket in buckets:
        headers["X-Bucket-Name"] = bucket
        
        print(f"Uploading {filename} to {endpoint} with {args.partsize} megabytes per part. Bucket: {bucket}")

        # # Upload the file
        upload_file(endpoint, filename, partsize, headers)

if __name__ == "__main__":
    main()