from airflow.sdk import dag, task


@dag(
    schedule=None,  # "@once"
    description="A dag to test xcom",
)
def test_xcom():

    @task
    def get_jobs():
        return {"something": "job"}

    @task
    def register():
        from airflow.sdk import get_current_context

        context = get_current_context()
        dag_instance = context["dag"]
        task_instance = context["ti"]
        task_id = task_instance.task_id

        current_task = dag_instance.get_task(task_id)

        for upstream in current_task.upstream_list:
            get_jobs_xcom = task_instance.xcom_pull(task_ids=upstream.task_id)
            print(get_jobs_xcom)

    get_jobs() >> register()

test_xcom()
