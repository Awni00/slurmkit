Rough: If a user requests the creation of a job collection (e.g., by `slurmkit generate`) and the job collection name already exists, ask them whether they would like to:
1) add to existing collection
2) Create a new collection with a unique name (e.g., append current date-string to collection name)
3) delete existing collection and overwrite