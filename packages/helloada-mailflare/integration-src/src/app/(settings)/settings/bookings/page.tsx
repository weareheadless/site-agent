import BookingTypesPage from "@/app/(calendar)/booking/page";
import { BusinessBookingSettings } from "@/components/booking/business-settings";

export default function BookingSettingsPage() {
  return <div className="space-y-8">
    <BusinessBookingSettings />
    <BookingTypesPage />
  </div>;
}
