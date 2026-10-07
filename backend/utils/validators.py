def validate_user_id(user_id:int):
    if user_id<=0:
        raise ValueError("Invalid user ID")
    return user_id
def validate_incident_owner(incident_user_id:int,current_user_id:int):
    if incident_user_id!=current_user_id:
        return False
    return True
def serialize_incident(incident):
    return {
        "id":incident.id,
        "report_refernce":incident.report_refernce,
        "user_id":incident.user_id,
        "message":incident.message,
        "location":incident.location,
        "people_affected":incident.people_affected,
        "helf_requested":incident.help_requested,
        "status":incident.status,
        "created_at":incident.created_at,
        "updated_at":incident.updated_at
    }
