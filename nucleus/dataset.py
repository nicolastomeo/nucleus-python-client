import uuid
from typing import Any, Dict, List, Optional, Union

import requests

from nucleus.job import AsyncJob
from nucleus.utils import (
    format_dataset_item_response,
    serialize_and_write_to_presigned_url,
)

from .annotation import Annotation
from .constants import (
    DATASET_ITEM_IDS_KEY,
    DATASET_LENGTH_KEY,
    DATASET_MODEL_RUNS_KEY,
    DATASET_NAME_KEY,
    DATASET_SLICES_KEY,
    DEFAULT_ANNOTATION_UPDATE_MODE,
    NAME_KEY,
    REFERENCE_IDS_KEY,
    REQUEST_ID_KEY,
    UPDATE_KEY,
)
from .dataset_item import DatasetItem, check_all_paths_remote
from .payload_constructor import construct_model_run_creation_payload


class Dataset:
    """
    Nucleus Dataset. You can append images with metadata to your dataset,
    annotate it with ground truth and upload model predictions to evaluate and
    compare model performance on you data.
    """

    def __init__(
        self,
        dataset_id: str,
        client: "NucleusClient",  # type:ignore # noqa: F821
    ):
        self.id = dataset_id
        self._client = client

    def __repr__(self):
        return f"Dataset(dataset_id='{self.id}', client={self._client})"

    def __eq__(self, other):
        if self.id == other.id:
            if self._client == other._client:
                return True
        return False

    @property
    def name(self) -> str:
        return self.info().get(DATASET_NAME_KEY, "")

    @property
    def model_runs(self) -> List[str]:
        return self.info().get(DATASET_MODEL_RUNS_KEY, [])

    @property
    def slices(self) -> List[str]:
        return self.info().get(DATASET_SLICES_KEY, [])

    @property
    def size(self) -> int:
        return self.info().get(DATASET_LENGTH_KEY, 0)

    @property
    def items(self) -> List[DatasetItem]:
        return self._client.get_dataset_items(self.id)

    def autotag_scores(self, autotag_name, for_scores_greater_than=0):
        """Export the autotag scores above a threshold, largest scores first.

        If you have pandas installed, you can create a pandas dataframe using

        pandas.Dataframe(dataset.autotag_scores(autotag_name))

        :return: dictionary of the form
            {'ref_ids': List[str],
             'datset_item_ids': List[str],
             'score': List[float]}
        """
        response = self._client.make_request(
            payload={},
            route=f"autotag/{self.id}/{autotag_name}/{for_scores_greater_than}",
            requests_command=requests.get,
        )
        return response

    def info(self) -> dict:
        """
        Returns information about existing dataset
        :return: dictionary of the form
            {
                'name': str,
                'length': int,
                'model_run_ids': List[str],
                'slice_ids': List[str]
            }
        """
        return self._client.dataset_info(self.id)

    def create_model_run(
        self,
        name: str,
        reference_id: Optional[str] = None,
        model_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        annotation_metadata_schema: Optional[Dict] = None,
    ):
        """
        :param name: A name for the model run.
        :param reference_id: The user-specified reference identifier to associate with the model.
                        The 'model_id' field should be empty if this field is populated,
        :param model_id: The internally-controlled identifier of the model.
                    The 'reference_id' field should be empty if this field is populated,
        :param metadata: An arbitrary metadata blob for the current run.
        :param annotation_metadata_schema: A dictionary that defines schema for annotations.
        :param segmentation_metadata_schema: A dictionary that defines schema for segmentation.

        :return:
        {
          "model_id": str,
          "model_run_id": str,
        }
        """
        payload = construct_model_run_creation_payload(
            name,
            reference_id,
            model_id,
            metadata,
            annotation_metadata_schema,
        )
        return self._client.create_model_run(self.id, payload)

    def annotate(
        self,
        annotations: List[Annotation],
        update: Optional[bool] = DEFAULT_ANNOTATION_UPDATE_MODE,
        batch_size: int = 5000,
    ) -> dict:
        """
        Uploads ground truth annotations for a given dataset.
        :param annotations: ground truth annotations for a given dataset to upload
        :param batch_size: batch parameter for long uploads
        :return:
        {
            "dataset_id: str,
            "new_items": int,
            "updated_items": int,
            "ignored_items": int,
        }
        """
        return self._client.annotate_dataset(
            self.id, annotations, update=update, batch_size=batch_size
        )

    def ingest_tasks(self, task_ids: dict):
        """
        If you already submitted tasks to Scale for annotation this endpoint ingests your completed tasks
        annotated by Scale into your Nucleus Dataset.
        Right now we support ingestion from Videobox Annotation and 2D Box Annotation projects.
        Lated we'll support more annotation types.
        :param task_ids: list of task ids
        :return: {"ingested_tasks": int, "ignored_tasks": int, "pending_tasks": int}
        """
        return self._client.ingest_tasks(self.id, {"tasks": task_ids})

    def append(
        self,
        dataset_items: List[DatasetItem],
        update: Optional[bool] = False,
        batch_size: Optional[int] = 20,
        asynchronous=False,
    ) -> Union[dict, AsyncJob]:
        """
        Appends images with metadata (dataset items) to the dataset. Overwrites images on collision if forced.

        Parameters:
        :param dataset_items: items to upload
        :param update: if True overwrites images and metadata on collision
        :param batch_size: batch parameter for long uploads
        :param aynchronous: if True, return a job object representing asynchronous ingestion job.
        :return:
        {
            'dataset_id': str,
            'new_items': int,
            'updated_items': int,
            'ignored_items': int,
        }
        """
        if asynchronous:
            check_all_paths_remote(dataset_items)
            request_id = uuid.uuid4().hex
            response = self._client.make_request(
                payload={},
                route=f"dataset/{self.id}/signedUrl/{request_id}",
                requests_command=requests.get,
            )
            print(response["signed_url"])

            serialize_and_write_to_presigned_url(
                dataset_items, response["signed_url"]
            )
            response = self._client.make_request(
                payload={REQUEST_ID_KEY: request_id, UPDATE_KEY: update},
                route=f"dataset/{self.id}/append?async=1",
            )
            return AsyncJob(response["job_id"], self._client)

        return self._client.populate_dataset(
            self.id,
            dataset_items,
            force=update,
            batch_size=batch_size,
        )

    def iloc(self, i: int) -> dict:
        """
        Returns Dataset Item Info By Dataset Item Number.
        :param i: absolute number of dataset item for the given dataset.
        :return:
        {
            "item": DatasetItem,
            "annotations": List[Union[BoxAnnotation, PolygonAnnotation]],
        }
        """
        response = self._client.dataitem_iloc(self.id, i)
        return format_dataset_item_response(response)

    def refloc(self, reference_id: str) -> dict:
        """
        Returns Dataset Item Info By Dataset Item Reference Id.
        :param reference_id: reference_id of dataset item.
        :return:
        {
            "item": DatasetItem,
            "annotations": List[Union[BoxAnnotation, PolygonAnnotation]],
        }
        """
        response = self._client.dataitem_ref_id(self.id, reference_id)
        return format_dataset_item_response(response)

    def loc(self, dataset_item_id: str) -> dict:
        """
        Returns Dataset Item Info By Dataset Item Id.
        :param dataset_item_id: internally controlled id for the dataset item.
        :return:
        {
            "item": DatasetItem,
            "annotations": List[Union[BoxAnnotation, PolygonAnnotation]],
        }
        """
        response = self._client.dataitem_loc(self.id, dataset_item_id)
        return format_dataset_item_response(response)

    def create_slice(
        self,
        name: str,
        dataset_item_ids: List[str] = None,
        reference_ids: List[str] = None,
    ):
        """
        Creates a slice from items already present in a dataset.
        The caller must exclusively use either datasetItemIds or reference_ids
        as a means of identifying items in the dataset.

        :param name: The human-readable name of the slice.
        :param dataset_item_ids: An optional list of dataset item ids for the items in the slice
        :param reference_ids: An optional list of user-specified identifier for the items in the slice

        :return: new Slice object
        """
        if bool(dataset_item_ids) == bool(reference_ids):
            raise Exception(
                "You must specify exactly one of dataset_item_ids or reference_ids."
            )
        payload: Dict[str, Any] = {NAME_KEY: name}
        if dataset_item_ids:
            payload[DATASET_ITEM_IDS_KEY] = dataset_item_ids
        if reference_ids:
            payload[REFERENCE_IDS_KEY] = reference_ids
        return self._client.create_slice(self.id, payload)

    def delete_item(self, item_id: str = None, reference_id: str = None):
        if bool(item_id) == bool(reference_id):
            raise Exception(
                "You must specify either a reference_id or an item_id for a DatasetItem."
            )
        return self._client.delete_dataset_item(
            self.id, reference_id=reference_id, item_id=item_id
        )

    def list_autotags(self):
        return self._client.list_autotags(self.id)

    def create_custom_index(self, embeddings_url: str):
        return self._client.create_custom_index(self.id, embeddings_url)

    def delete_custom_index(self):
        return self._client.delete_custom_index(self.id)

    def check_index_status(self, job_id: str):
        return self._client.check_index_status(job_id)
