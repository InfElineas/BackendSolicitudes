# app/utils/mongo_helpers.py
from bson import ObjectId

def fix_mongo_id(doc):
    """
    Convierte ObjectId de MongoDB en string para que FastAPI pueda serializarlo.
    Soporta dicts, listas y documentos anidados.
    """
    if not doc:
        return doc

    if isinstance(doc, list):
        return [fix_mongo_id(d) for d in doc]

    if isinstance(doc, dict):
        new_doc = {}
        for k, v in doc.items():
            if isinstance(v, ObjectId):
                new_doc[k] = str(v)
            else:
                new_doc[k] = fix_mongo_id(v)
        return new_doc

    return doc
