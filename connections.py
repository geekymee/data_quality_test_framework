import io
import time
import logging
import boto3
import pandas as pd
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class AthenaConnector:
    POLL_INTERVAL_SECONDS = 2
    TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}

    def __init__(self, region: str, s3_output_location: str, workgroup: str = "primary"):
        self.region             = region
        self.s3_output_location = s3_output_location
        self.workgroup          = workgroup
        self.client             = boto3.client("athena", region_name=region)
        logger.info(f"AthenaConnector initialised — region={region}, workgroup={workgroup}")

    def run_query(self, sql: str, database: str) -> pd.DataFrame:
        execution_id = self._start_query(sql, database)
        logger.info(f"Query submitted — ExecutionId={execution_id}")
        self._wait_for_completion(execution_id)
        df = self._fetch_results(execution_id)
        logger.info(f"Query returned {len(df)} row(s) — ExecutionId={execution_id}")
        return df

    def get_table_schema(self, database: str, table: str) -> pd.DataFrame:
        return self.run_query(f"DESCRIBE {database}.{table}", database)

    def _start_query(self, sql: str, database: str) -> str:
        response = self.client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": database},
            ResultConfiguration={"OutputLocation": self.s3_output_location},
            WorkGroup=self.workgroup,
        )
        return response["QueryExecutionId"]

    def _wait_for_completion(self, execution_id: str) -> None:
        while True:
            response = self.client.get_query_execution(QueryExecutionId=execution_id)
            state    = response["QueryExecution"]["Status"]["State"]
            if state in self.TERMINAL_STATES:
                if state != "SUCCEEDED":
                    reason = response["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
                    raise RuntimeError(
                        f"Athena query {execution_id} ended with state={state}. Reason: {reason}"
                    )
                return
            logger.debug(f"Query {execution_id} state={state}, waiting …")
            time.sleep(self.POLL_INTERVAL_SECONDS)

    def _fetch_results(self, execution_id: str) -> pd.DataFrame:
        paginator = self.client.get_paginator("get_query_results")
        pages     = paginator.paginate(QueryExecutionId=execution_id)

        rows, header = [], None
        for page in pages:
            result_rows = page["ResultSet"]["Rows"]
            if header is None:
                header      = [col["VarCharValue"] for col in result_rows[0]["Data"]]
                result_rows = result_rows[1:]
            for row in result_rows:
                rows.append([cell.get("VarCharValue", None) for cell in row["Data"]])

        return pd.DataFrame(rows, columns=header) if header else pd.DataFrame()

class S3Connector:

    def __init__(self, region: str):
        self.region   = region
        self.client   = boto3.client("s3", region_name=region)
        self.resource = boto3.resource("s3", region_name=region)
        logger.info(f"S3Connector initialised — region={region}")

    def upload_dataframe_as_csv(
        self, df: pd.DataFrame, bucket: str, key: str, index: bool = False
    ) -> str:
        buffer = io.StringIO()
        df.to_csv(buffer, index=index)
        self.client.put_object(
            Bucket=bucket, Key=key,
            Body=buffer.getvalue().encode("utf-8"),
            ContentType="text/csv",
        )
        uri = f"s3://{bucket}/{key}"
        logger.info(f"Uploaded {len(df)} row(s) → {uri}")
        return uri

    def upload_file(self, local_path: str, bucket: str, key: str) -> str:
        self.client.upload_file(local_path, bucket, key)
        uri = f"s3://{bucket}/{key}"
        logger.info(f"Uploaded file {local_path} → {uri}")
        return uri

    def download_csv_as_dataframe(self, bucket: str, key: str) -> pd.DataFrame:
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return pd.read_csv(io.BytesIO(obj["Body"].read()))

    def read_local_csv(self, path: str) -> pd.DataFrame:
        return pd.read_csv(path)

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

def get_connectors(region: str, athena_s3_output: str, workgroup: str = "primary"):
    return (
        AthenaConnector(region=region, s3_output_location=athena_s3_output, workgroup=workgroup),
        S3Connector(region=region),
    )
