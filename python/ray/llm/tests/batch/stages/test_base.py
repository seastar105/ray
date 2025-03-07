import sys
import pytest
from typing import List, Any, AsyncIterator, Dict
from ray.llm._internal.batch.stages.base import (
    wrap_preprocess,
    wrap_postprocess,
    StatefulStage,
    StatefulStageUDF,
)


def test_wrap_preprocess():
    # Test function that doubles a number
    def double(x: dict) -> dict:
        return {"value": x["id"] * 2}

    # Test with carry_over=True
    wrapped = wrap_preprocess(double, "__data")
    result = wrapped({"id": 5, "extra": "memo"})
    assert result == {"__data": {"id": 5, "extra": "memo", "value": 10}}


def test_wrap_postprocess():
    # Test function that converts number to string
    def to_string(x: dict) -> dict:
        return {
            "result": str(x["value"]),
            "extra": x["extra"],
        }

    # Test with carry_over=True
    wrapped = wrap_postprocess(to_string, "__data")
    result = wrapped({"__data": {"id": 5, "extra": "memo", "value": 10}})
    assert result == {"extra": "memo", "result": "10"}

    # Test missing input column
    with pytest.raises(ValueError):
        wrapped({"wrong_key": 42})


class TestStatefulStageUDF:
    class SimpleUDF(StatefulStageUDF):
        def __init__(
            self,
            data_column: str,
            udf_output_missing_idx_in_batch_column: bool = False,
        ):
            super().__init__(data_column)
            self.udf_output_missing_idx_in_batch_column = (
                udf_output_missing_idx_in_batch_column
            )

        async def udf(
            self, rows: list[Dict[str, Any]]
        ) -> AsyncIterator[Dict[str, Any]]:

            # Intentionally output in a reversed order to test OOO.
            for row in rows[::-1]:
                ret = {"processed": row["value"] * 2}
                if not self.udf_output_missing_idx_in_batch_column:
                    ret[self.IDX_IN_BATCH_COLUMN] = row[self.IDX_IN_BATCH_COLUMN]
                yield ret

        @property
        def expected_input_keys(self) -> List[str]:
            return ["value"]

    @pytest.mark.asyncio
    async def test_basic_processing(self):
        udf = self.SimpleUDF(data_column="__data")

        batch = {
            "__data": [{"value": 1, "extra": 10}, {"value": 2, "extra": 20}],
        }

        results = []
        async for result in udf(batch):
            results.append(result)

        assert len(results) == 2
        for result in results:
            data = result["__data"][0]
            val = data["value"]
            assert data["processed"] == val * 2
            assert data["extra"] == 10 * val
            assert data["value"] == val

    @pytest.mark.asyncio
    async def test_missing_data_column(self):
        udf = self.SimpleUDF(data_column="__data")

        batch = {"extra": ["a"]}

        with pytest.raises(ValueError):
            async for _ in udf(batch):
                pass

    @pytest.mark.asyncio
    async def test_missing_required_key(self):
        udf = self.SimpleUDF(data_column="__data")

        batch = {"__data": [{"wrong_key": 1}]}

        with pytest.raises(ValueError):
            async for _ in udf(batch):
                pass

    @pytest.mark.asyncio
    async def test_missing_idx_in_batch_column(self):
        udf = self.SimpleUDF(
            data_column="__data",
            udf_output_missing_idx_in_batch_column=True,
        )

        batch = {"__data": [{"value": 1}]}

        with pytest.raises(ValueError):
            async for _ in udf(batch):
                pass


def test_stateful_stage():
    udf = TestStatefulStageUDF.SimpleUDF(data_column="__data")

    stage = StatefulStage(
        fn=udf,
        fn_constructor_kwargs={"data_column": "__data"},
        map_batches_kwargs={"batch_size": 10},
    )

    assert stage.fn == udf
    assert stage.fn_constructor_kwargs == {"data_column": "__data"}
    assert stage.map_batches_kwargs == {"batch_size": 10}


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
