from enum import Enum


class DistanceMetricEnums(Enum):
    COSINE = "cosine"
    DOT = "dot"


class PgvectorTableSchemaEnums(Enum):
    ID = "id"
    CHUNK_ID = "chunk_id"
    TEXT = "text"            # what is embedded: header + text
    RAW_TEXT = "raw_text"    # what the screen shows and the checker reads
    VECTOR = "embedding"
    METADATA = "metadata"
    TSV = "tsv"


class PgvectorDistanceMetricEnums(Enum):
    COSINE = "vector_cosine_ops"
    L2 = "vector_l2_ops"


class PgvectorIndexTypeEnums(Enum):
    IVFFLAT = "ivfflat"
    HNSW = "hnsw"
