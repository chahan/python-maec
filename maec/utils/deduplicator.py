# MAEC Bundle Deduplicator Module
# Last updated: 12/3/2013
import collections
import cybox
import sets
import copy
from cybox.common.properties import BaseProperty

class BundleDeduplicator(object):
    @classmethod
    def deduplicate(cls, bundle):
        # Dictionary of all unique objects
        # Key = object type (xsi:type)
        # Value = dictionary of unique objects for that type
        #   Key = unique object id
        #   Value = object values, as a set
        cls.objects_dict = {}
        # Dictionary of non-unique -> unique Object ID mappings
        cls.object_ids_mapping = {}
        # Get all Objects in the Bundle
        all_objects = bundle.get_all_objects(include_actions=True)
        # Perform the Object mapping
        cls.map_objects(all_objects)
        # Do the actual deduplication if duplicate objects were found
        if cls.object_ids_mapping:
            # Next, add the unique objects to their own collection
            cls.handle_unique_objects(bundle, all_objects)
            # Replace the non-unique Objects with references 
            # to unique Objects across the entire Bundle
            cls.handle_duplicate_objects(bundle, all_objects)
            # Finally, perform some cleanup to handle strange
            # cases where you may have Objects pointing to each other
            cls.cleanup(bundle)

    # Cleanup and remove and Objects that may be referencing the re-used Objects
    # Otherwise, this can create Object->Object->Object etc. references which don't make sense
    @classmethod
    def cleanup(cls, bundle):
        # Cleanup the root-level Objects
        if bundle.objects:
            # List of Objects to remove
            objs = [x for x in bundle.objects if (x.idref and x.idref in cls.object_ids_mapping.values())]
            # Remove the extraneous Objects
            for obj in objs:
                bundle.objects.remove(obj)
        # Cleanup the Object Collections
        if bundle.collections and bundle.collections.object_collections:
            for collection in bundle.collections.object_collections:
                # Ignore the re-used objects collection
                if collection.name and collection.name == "Deduplicated Objects":
                    continue

                # List of Objects to remove
                objs = [x for x in collection.object_list if (x.idref and x.idref in cls.object_ids_mapping.values())]

                for obj in objs:
                    collection.object_list.remove(obj)

    # Replace all of the duplicate Objects with references to
    # the unique object placed in the "Re-used Objects" Collection
    @classmethod
    def handle_duplicate_objects(cls, bundle, all_objects):
        for duplicate_object_id, unique_object_id in cls.object_ids_mapping.items():
            for object in all_objects:
                if object.id_ == duplicate_object_id or object.idref == duplicate_object_id:
                    # Modify the existing Object to serve as a reference to
                    # the unique Object in the collection
                    object.idref = unique_object_id
                    object.id_ = None
                    object.properties = None
                    object.related_objects = None
                    object.domain_specific_object_properties = None

    # Add a new Object collection to the Bundle for storing the unique Objects
    # Add the Objects to said collection
    @classmethod
    def handle_unique_objects(cls, bundle, all_objects):
        # First, find the ID of the last Object Collection (if applicable)
        counter = 1
        if bundle.collections and bundle.collections.object_collections:
            for object_collection in bundle.collections.object_collections:
                counter += 1
        # Find the namespace used in the Bundle IDs
        bundle_namespace = bundle.id.split('-')[1]
        # Build the collection ID
        collection_id = "maec-" + bundle_namespace + "-objc-" + str(counter)
        # Add the named Object collection
        bundle.add_named_object_collection("Deduplicated Objects", collection_id)
        # Add the unique Objects to the collection
        cls.add_unique_objects(bundle, all_objects)

    # Add the unique Objects to the collection and perform the properties replacement
    @classmethod
    def add_unique_objects(cls, bundle, all_objects):
        added_ids = []
        for unique_object_id in cls.object_ids_mapping.values():
            if unique_object_id not in added_ids:
                for object in all_objects:
                    if object.id_ and object.id_ == unique_object_id:
                        object_copy = copy.deepcopy(object)
                        if isinstance(object_copy, cybox.core.AssociatedObject):
                            object_copy.association_type = None
                        elif isinstance(object_copy, cybox.core.RelatedObject):
                            object_copy.relationship = None
                        # Modify the existing Object to serve as a reference to the Object in the collection
                        object.idref = object.id_
                        object.id_ = None
                        object.properties = None
                        object.related_objects = None
                        object.domain_specific_object_properties = None
                        # Add the unique Object to the collection
                        bundle.add_object(object_copy, "Deduplicated Objects")
                        # Break out of the all_objects loop
                        break
                added_ids.append(unique_object_id)

    # Map the non-unique Objects to their unique (first observed) counterparts
    @classmethod
    def map_objects(cls, all_objects):
        # Do the object mapping
        for obj in all_objects:
            matching_object_id = cls.find_matching_object(obj)
            if matching_object_id:
                cls.object_ids_mapping[obj.id_] = matching_object_id

    # Returns the value contained in a TypedField or its nested members, if applicable
    @classmethod
    def get_typedfield_values(cls, val, name, values):
        # If it's a BaseProperty instance, then we're done. Return it.
        if isinstance(val, BaseProperty):
            values.add(name + ":" + str(val))
        # If it's a list, then we need to iterate through each of its members
        elif isinstance(val, collections.MutableSequence):
            for list_item in val:
                for list_item_property in list_item._get_vars():
                    cls.get_typedfield_values(getattr(list_item, str(list_item_property)), name + "/" + str(list_item_property), values)
        # If it's a cybox.Entity, then we need to iterate through its properties
        elif isinstance(val, cybox.Entity):
            for item_property in val._get_vars():
                cls.get_typedfield_values(getattr(val, str(item_property)), name + "/" + str(item_property), values) 

    # Get the values specified for an object's properties as a set
    @classmethod
    def get_object_values(cls, obj):
        values = set()
        for typed_field in obj.properties._get_vars():
            # Make sure the typed field is comparable
            if typed_field.comparable:
                val = getattr(obj.properties, str(typed_field))
                if val is not None:
                    cls.get_typedfield_values(val, str(typed_field), values)
        return values

    # Find a matching object, if it exists
    @classmethod
    def find_matching_object(cls, obj):
        if obj and obj.properties:
            object_values = cls.get_object_values(obj)
            xsi_type = obj.properties._XSI_TYPE 
            if xsi_type and xsi_type in cls.objects_dict:
                types_dict = cls.objects_dict[xsi_type]
                # See if we already have an identical object in the dictionary
                for obj_id, obj_values in types_dict.items():
                    if obj_values == object_values:
                        # If so, return its ID for use in the IDREF
                        return obj_id
                # If not, add it to the dictionary
                types_dict[obj.id_] = object_values
            elif xsi_type and xsi_type not in cls.objects_dict:
                types_dict = {obj.id_:object_values}
                cls.objects_dict[xsi_type] = types_dict
            return None
