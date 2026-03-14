"""Sample Airflow DAG for testing the Hydrologist."""
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from datetime import datetime


def dummy():
    pass


with DAG(dag_id="sample_pipeline", start_date=datetime(2024, 1, 1)) as dag:
    extract = PythonOperator(task_id="extract", python_callable=dummy)
    transform = BashOperator(task_id="transform", bash_command="echo transform")
    load = PythonOperator(task_id="load", python_callable=dummy)
    extract >> transform >> load
