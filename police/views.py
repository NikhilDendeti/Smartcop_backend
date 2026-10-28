from django.shortcuts import render
from rest_framework import status
from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from police.interactors.get_head_constable_details import GetHeadConstableDetailsByPhoneInteractor
from police.interactors.si_login import SiLoginInteractor
from police.interactors.get_si_profile import GetSiProfileInteractor
from police.interactors.list_all_complaints import ListAllComplaintsInteractor
from police.interactors.get_complaint_details import GetComplaintDetailsInteractor
from police.interactors.assign_complaint_to_hc import AssignComplaintToHCInteractor
from police.interactors.mark_under_investigation import MarkUnderInvestigationInteractor
from police.interactors.list_head_constables import ListHeadConstablesInteractor
from police.interactors.update_complaint_status import UpdateComplaintStatusInteractor


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def get_head_constable_profile_view(request):
    phone = request.query_params.get("phone")

    if not phone:
        return Response({"error": "Phone number is required"}, status=400)

    try:
        interactor = GetHeadConstableDetailsByPhoneInteractor(phone)
        result = interactor.execute()
        return Response(result, status=200)
    except ValueError as ve:
        return Response({"error": str(ve)}, status=403)
    except Exception:
        return Response({"error": "Something went wrong"}, status=500)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def si_login_view(request):
    phone = request.data.get("phone")
    otp = int(request.data.get("otp"))

    interactor = SiLoginInteractor(phone, otp)
    result = interactor.execute()

    status_code = 200 if result.get("status") == "success" else 400
    return Response(result, status=status_code)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def get_si_profile_view(request):
    phone = request.GET.get('phone')
    if not phone:
        return Response({"error": "Phone number is required", "status": "failed"}, status=400)

    try:
        interactor = GetSiProfileInteractor(phone)
        result = interactor.execute()
        return Response(result, status=200)
    except ValueError as ve:
        return Response({"error": str(ve), "status": "failed"}, status=404)
    except Exception:
        return Response({"error": "Something went wrong", "status": "failed"}, status=500)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def get_all_complaints_view(request):
    try:
        interactor = ListAllComplaintsInteractor()
        result = interactor.execute()
        return Response(result, status=200)
    except Exception:
        return Response({"status": "failed", "error": "Server error"}, status=500)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def get_complaint_details_si_view(request, complaint_id):
    interactor = GetComplaintDetailsInteractor(complaint_id)
    result = interactor.execute()

    status_code = 404 if result.get("error") else 200
    return Response(result, status=status_code)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def assign_complaint_to_hc_view(request):
    try:
        complaint_id = request.data.get("complaint_id")
        hc_phone = request.data.get("head_constable_phone")
        si_phone = request.data.get("si_phone")
        notes = request.data.get("notes", "")

        interactor = AssignComplaintToHCInteractor(
            complaint_id=complaint_id,
            hc_phone=hc_phone,
            si_phone=si_phone,
            notes=notes
        )

        result = interactor.execute()
        return Response(result, status=200)

    except ValueError as ve:
        return Response({"status": "failed", "error": str(ve)}, status=400)
    except Exception:
        return Response({"status": "failed", "error": "Internal server error"}, status=500)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def mark_under_investigation_view(request):
    try:
        complaint_id = request.data.get("complaint_id")
        si_phone = request.data.get("si_phone")
        remarks = request.data.get("remarks", "")

        interactor = MarkUnderInvestigationInteractor(
            complaint_id=complaint_id,
            si_phone=si_phone,
            remarks=remarks
        )
        result = interactor.execute()
        return Response(result, status=200)

    except ValueError as ve:
        return Response({"status": "failed", "error": str(ve)}, status=400)
    except Exception:
        return Response({"status": "failed", "error": "Internal server error"}, status=500)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def list_head_constables_view(request):
    si_phone = request.query_params.get("si_phone")
    if not si_phone:
        return Response({"status": "failed", "error": "SI phone is required"}, status=400)

    try:
        interactor = ListHeadConstablesInteractor(si_phone)
        result = interactor.execute()
        return Response(result, status=200)
    except ValueError as ve:
        return Response({"status": "failed", "error": str(ve)}, status=404)
    except Exception:
        return Response({"status": "failed", "error": "Server error"}, status=500)

@api_view(["POST"])
@permission_classes([])  # Add permissions as needed
def update_complaint_status_view(request):
    try:
        complaint_id = request.data.get("complaint_id")
        new_status = request.data.get("status")

        if not complaint_id or not new_status:
            return Response({"error": "complaint_id and status are required"}, status=status.HTTP_400_BAD_REQUEST)

        interactor = UpdateComplaintStatusInteractor(complaint_id, new_status)
        complaint = interactor.execute()

        return Response({
            "message": "Complaint status updated successfully",
            "complaint_id": str(complaint.complaint_id),
            "new_status": complaint.status
        }, status=status.HTTP_200_OK)

    except ValidationError as ve:
        return Response({"error": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
