import { useLocalSearchParams, useRouter } from "expo-router";
import { ResetPasswordForm } from "../../components/ResetPasswordForm";
import { Screen } from "../../components/ui";

export default function Reset() {
  const router = useRouter();
  const { email } = useLocalSearchParams<{ email?: string }>();
  return (
    <Screen>
      <ResetPasswordForm
        email={email ?? ""}
        onResend={() => router.replace("/(auth)/forgot")}
        onDone={() => router.replace("/(auth)/login")}
      />
    </Screen>
  );
}
