from django.conf import settings
from django.shortcuts import render

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from users.models import User
from users.interactors.get_user_details import GetUserDetailsInteractor
from users.interactors.create_case_type import CreateCaseTypeInteractor
from users.interactors.create_current_address import UpdateCurrentAddressInteractor
from users.utils.ai_predictor import get_ai_assessment
from users.interactors.create_complaint import CreateComplaintInteractor
from users.interactors.create_non_cognizable_complaint import CreateNonCognizableComplaintInteractor
from users.interactors.get_user_complaints import GetUserComplaintsInteractor
from users.interactors.get_complaint_details import GetComplaintDetailsInteractor

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def get_user_details(request):
    phone_number = request.data.get('phone_number')

    if not phone_number:
        return Response({"error": "Phone number is required"}, status=status.HTTP_400_BAD_REQUEST)

    interactor = GetUserDetailsInteractor(phone_number=phone_number)
    user_data = interactor.execute()

    if user_data.get("status") == "success":
        return Response(user_data, status=status.HTTP_200_OK)
    if user_data.get("error") == "User not found":
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"error": user_data.get("error", "Authentication failed")}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['POST'])
@authentication_classes([])  # You can restrict this to admin later
@permission_classes([])
def create_case_type_view(request):
    name = request.data.get("name")

    if not name:
        return Response({"error": "Case type name is required."}, status=status.HTTP_400_BAD_REQUEST)

    interactor = CreateCaseTypeInteractor()
    case_type = interactor.create_case_type(name=name)

    return Response({
        "case_type_id": str(case_type.case_type_id),
        "name": case_type.name,
        "message": "Case type created or returned successfully."
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def update_current_address_view(request):
    phone_number = request.data.get("phone_number")
    current_address = request.data.get("current_address")

    if not phone_number or not current_address:
        return Response({"error": "Phone number and current address are required"}, status=status.HTTP_400_BAD_REQUEST)

    interactor = UpdateCurrentAddressInteractor(phone_number, current_address)
    result = interactor.update_current_address()

    if result["success"]:
        return Response(result, status=status.HTTP_200_OK)
    else:
        return Response(result, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def ai_assessment_view(request):
    incident_summary = request.data.get("incident_summary")

    if not incident_summary:
        return Response({"error": "incident_summary is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = get_ai_assessment(incident_summary)
        return Response(result, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def create_complaint_view(request):
    try:
        user_id = request.data.get("user_id") or settings.LEGACY_DEFAULT_USER_ID
        if not user_id:
            return Response({"error": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.get(user_id=user_id)

        interactor = CreateComplaintInteractor(data=request.data, user=user)
        complaint = interactor.execute()

        return Response({
            "message": "Complaint created successfully",
            "complaint_id": str(complaint.complaint_id)
        }, status=status.HTTP_201_CREATED)

    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def get_complaint_details_view(request, complaint_id):
    interactor = GetComplaintDetailsInteractor(complaint_id)
    result = interactor.get_complaint_details()

    if result:
        return Response(result, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Complaint not found"}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def create_non_cognizable_complaint_view(request):
    try:
        interactor = CreateNonCognizableComplaintInteractor(data=request.data)
        result = interactor.create()
        return Response(result, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def list_user_complaints(request, user_id):
    interactor = GetUserComplaintsInteractor(user_id)
    result = interactor.execute()
    return Response(result)
